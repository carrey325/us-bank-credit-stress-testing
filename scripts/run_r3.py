from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.artifacts import sha256_file, validate_artifact_metadata, write_artifact_metadata
from bankstress.modeling import load_model_specs
from bankstress.r3 import (
    build_model_use_registry, prediction_target_dictionary, run_historical_validation,
    run_one_step_quantiles, validate_target_dictionary,
)

R2_RUN_ID = "r2-20260907T194522Z"
RUN_ID = "r3-20260907-jumpoff-lineage-repair"


def _write_target_dictionary(rows: list[dict]) -> Path:
    path = ROOT / "outputs/repair/r3/prediction_target_dictionary.md"
    lines = ["# R3 prediction target dictionary", "",
             "These targets are not interchangeable. Fixed-quantile recursive feedback is never a calibrated multi-period tail distribution.", ""]
    for row in rows:
        labels = [f"status={row['status']}"]
        if row.get("nominal_coverage") is not None:
            labels.append(f"nominal_coverage={row['nominal_coverage']:.0%}")
        if row.get("nominal_exceedance_rate") is not None:
            labels.append(f"nominal_exceedance_rate={row['nominal_exceedance_rate']:.0%}")
        lines.extend([f"## `{row['target_id']}`", "", row["definition"], "", ", ".join(labels), ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    out, validation = ROOT / "outputs/repair/r3", ROOT / "outputs/validation"
    out.mkdir(parents=True, exist_ok=True)
    validation.mkdir(parents=True, exist_ok=True)
    r2_summary = ROOT / "outputs/repair/r2/validation_summary.json"
    r2_meta = validate_artifact_metadata(r2_summary, expected_stage="R2")
    r2 = json.loads(r2_summary.read_text(encoding="utf-8"))
    if r2["run_id"] != R2_RUN_ID or r2["validation_status"] != "PASS":
        raise ValueError("R3 requires the approved passing R2 run")
    panel_path = ROOT / "data/derived/model_panel.parquet"
    panel_meta = validate_artifact_metadata(panel_path, expected_stage="R2")
    if r2_meta["input_artifact_hashes"][panel_path.relative_to(ROOT).as_posix()] != sha256_file(panel_path):
        raise ValueError("R2 summary does not bind the current model panel")
    panel = pd.read_parquet(panel_path)
    spec = load_model_specs(ROOT)
    targets = prediction_target_dictionary()
    validate_target_dictionary(targets)
    predictions, tail_metrics, diagnostics = run_one_step_quantiles(panel, spec)
    paths, historical_metrics, support = run_historical_validation(panel, spec)
    predictions.to_parquet(validation / "oos_predictions.parquet", index=False)
    tail_metrics.to_csv(validation / "tail_metrics.csv", index=False)
    diagnostics.to_csv(validation / "quantile_fit_diagnostics.csv", index=False)
    paths.to_parquet(validation / "pseudo_stress.parquet", index=False)
    historical_metrics.to_csv(validation / "pseudo_stress_metrics.csv", index=False)
    support.to_csv(validation / "pseudo_stress_training_support.csv", index=False)
    methodology_path = validation / "pseudo_stress_methodology.yaml"
    methodology_path.write_text(yaml.safe_dump({
        "validation_scope": "MINIMAL_R3",
        "macro_path": "supplied realized historical macro path; unavailable features are not imputed",
        "lagged_nco": "recursive modeled state after a valid jump-off",
        "bank_controls": "current train-end NPL rate, allowance coverage, Tier 1 ratio, and adjacent-quarter loan growth held fixed; incomplete current states are excluded and counted",
        "bank_control_source_lineage": "one source-period column per frozen control in pseudo_stress.parquet",
        "generation_scoring_separation": True,
        "conditional_mean_path_label": "plug-in conditional-mean recursive path; not asserted exact expectation",
        "fixed_quantile_feedback_label": "recursive_quantile_sensitivity_not_distribution",
        "multi_period_cumulative_loss_q90": "NOT_EVALUATED",
        "windows": spec["pseudo_stress_windows"],
    }, sort_keys=False), encoding="utf-8")
    target_path = _write_target_dictionary(targets)
    model_spec_hash = sha256_file(ROOT / "configs/model_specs.yaml")
    evidence = ["outputs/repair/r2/research_decision.md", "outputs/validation/tail_metrics.csv",
                "outputs/validation/quantile_fit_diagnostics.csv", "outputs/validation/pseudo_stress_metrics.csv",
                "outputs/validation/pseudo_stress_training_support.csv"]
    registry = build_model_use_registry(tail_metrics, historical_metrics, diagnostics, R2_RUN_ID, model_spec_hash, evidence)
    registry_path = validation / "model_use_registry.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    limitations_path = out / "validation_limitations.md"
    q90 = tail_metrics[(tail_metrics.tau.eq(0.9)) & (tail_metrics.prediction_version.eq("POST_REARRANGEMENT")) &
                       ~tail_metrics.window.eq(0)]
    crossing_total = int(diagnostics.groupby(["window", "segment", "model_family"]).crossing_rows_family_window.first().sum())
    limitations_path.write_text(
        "# Minimal R3 validation limitations\n\n"
        "- R2's negative findings are preserved: Dynamic FE improved equal-observation RMSE in 1/8 comparisons, and CRE amplification was not supported.\n"
        "- Bayesian validation, Q0.95/Q0.99, ML challengers, static-versus-rolling residual calibration, and multi-period density simulation are `NOT_EVALUATED`.\n"
        "- Q0.50-Q0.90 is a 40% band. No residual-calibrated two-sided 90% interval was regenerated.\n"
        "- One-step quantiles are diagnostic only; zero exceedances are not interpreted as success. Raw and rearranged forecasts are both retained.\n"
        f"- Independently fitted quantiles crossed in {crossing_total} model-family/window/segment row instances before rearrangement; this is retained as instability evidence.\n"
        "- Recursive mean paths condition on realized macro paths and frozen jump-off bank controls. They are plug-in paths, not asserted exact expectations.\n"
        "- Jump-off controls use current train-end values. Banks lacking a complete current NPL, allowance coverage, Tier 1 ratio, or adjacent-quarter loan-growth state are excluded and counted in `pseudo_stress_training_support.csv`.\n"
        "- Fixed-Q0.90 recursive paths are sensitivity diagnostics only. No cumulative-loss Q0.90 or multi-period tail distribution was computed.\n"
        "- Historical scoring uses available realized outcomes, while generation remains continuous when outcomes are unavailable. GFC training has few independent quarterly time points despite its cross-section.\n"
        f"- One-step post-rearrangement Q0.90 evaluation contains {int(q90.scored_n.sum())} scored bank-quarters across reported segment-windows; window-level exceedance counts and rates are in `tail_metrics.csv`.\n",
        encoding="utf-8",
    )
    quantile_spec_path = ROOT / "outputs/models/quantile/specification.yaml"
    quantile_spec_path.write_text(yaml.safe_dump({
        **spec["quantile_spec"], "quantiles": spec["quantiles"],
        "target_scope": "one_step_conditional_quantiles_only",
        "same_tau_baseline": "AR-only quantile with bank effects and lagged NCO",
        "prediction_versions": ["PRE_REARRANGEMENT", "POST_REARRANGEMENT"],
        "multi_period_tail_distribution": "NOT_EVALUATED",
    }, sort_keys=False), encoding="utf-8")
    required_paths = [validation / "oos_predictions.parquet", validation / "tail_metrics.csv",
                      validation / "quantile_fit_diagnostics.csv", validation / "pseudo_stress.parquet",
                      validation / "pseudo_stress_metrics.csv", validation / "pseudo_stress_training_support.csv",
                      methodology_path, quantile_spec_path, registry_path, target_path, limitations_path]
    required_paths.append(ROOT / "outputs/repair/artifact_status.json")
    quarterly_expected = support.expected_path_rows_per_model.sum() * 3
    summary = {
        "run_id": RUN_ID, "stage": "R3", "created_at": datetime.now(timezone.utc).isoformat(),
        "input_run_id": R2_RUN_ID, "input_model_panel_hash": sha256_file(panel_path),
        "r2_metadata_valid": True, "target_dictionary_valid": True,
        "quantile_taus": sorted(diagnostics.tau.unique().tolist()),
        "all_quantile_fits_converged": bool(diagnostics.converged.all()),
        "raw_quantile_crossing_rows": crossing_total,
        "raw_and_rearranged_predictions_preserved": set(predictions.prediction_version) == {"PRE_REARRANGEMENT", "POST_REARRANGEMENT"},
        "common_scoring_keys_verified": bool(tail_metrics.common_scoring_keys_verified.dropna().all()),
        "q90_nominal_exceedance_rate_valid": bool(np.isclose(
            tail_metrics[tail_metrics.tau.eq(0.9)].nominal_exceedance_rate.dropna().to_numpy(float), 0.1
        ).all()),
        "q50_q90_nominal_coverage_valid": bool(tail_metrics[tail_metrics.model_family.eq("dynamic_quantile_q50_q90_band")].nominal_coverage.eq(0.4).all()),
        "pseudo_windows": sorted(support.pseudo_window.unique().tolist()),
        "gfc_2005_start_verified": bool(support.gfc_2005_start_verified.all()),
        "future_control_leakage_count": int(support.future_control_leakage_count.sum()),
        "frozen_control_source_mismatch_count": int(support.frozen_control_source_mismatch_count.sum()),
        "jump_off_current_control_exclusions": int(support.jump_off_current_control_exclusions.sum()),
        "continuous_path_row_count": len(paths), "expected_continuous_path_row_count": int(quarterly_expected),
        "paths_preserved_with_missing_actual": int(paths.nco_rate.isna().sum()),
        "fixed_q90_feedback_labels_valid": bool(paths[paths.model_id.eq("dynamic_quantile_q90")].target_type.eq("recursive_quantile_sensitivity_not_distribution").all()),
        "multi_period_tail_distribution_authorizations": sum(row["multi_step_tail_distribution_use"] != "UNAVAILABLE" for row in registry),
        "residual_calibration_status": "NOT_EVALUATED", "bayesian_status": "NOT_EVALUATED",
        "research_result_status": {
            "r2_incremental_mean_benefit": "NOT_SUPPORTED",
            "r2_cre_amplification": "NOT_SUPPORTED",
            "one_step_tail_models": "INCONCLUSIVE_DIAGNOSTIC",
            "historical_conditional_mean_paths": "INCONCLUSIVE_WITH_USE_LIMITS",
            "multi_period_tail_distribution": "NOT_EVALUATED",
        },
    }
    failures = []
    for key in ["r2_metadata_valid", "target_dictionary_valid", "all_quantile_fits_converged", "raw_and_rearranged_predictions_preserved",
                "common_scoring_keys_verified", "q90_nominal_exceedance_rate_valid", "q50_q90_nominal_coverage_valid",
                "gfc_2005_start_verified", "fixed_q90_feedback_labels_valid"]:
        if not summary[key]: failures.append(key)
    if summary["future_control_leakage_count"]: failures.append("future_control_leakage_count")
    if summary["frozen_control_source_mismatch_count"]: failures.append("frozen_control_source_mismatch_count")
    if summary["continuous_path_row_count"] != summary["expected_continuous_path_row_count"]: failures.append("continuous_path_row_count")
    if summary["multi_period_tail_distribution_authorizations"]: failures.append("multi_period_tail_distribution_authorizations")
    summary["validation_failures"], summary["validation_status"] = failures, "PASS" if not failures else "FAIL"
    summary_path = out / "validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    required_paths.append(summary_path)
    run_summary_path = validation / "run_summary.md"
    run_summary_path.write_text(
        "# Minimal R3 run\n\n"
        f"- Run: `{RUN_ID}`; R2 input: `{R2_RUN_ID}`.\n"
        f"- Validation: `{summary['validation_status']}`; quantile fits converged: `{summary['all_quantile_fits_converged']}`.\n"
        "- Q0.50/Q0.75/Q0.90 are evaluated one step ahead against same-tau AR quantiles on common scoring keys.\n"
        "- Historical GFC/COVID/high-rate paths use current train-end bank controls, frozen with per-control source-quarter lineage; generation and scoring are separate.\n"
        "- Recursive Q0.90 is sensitivity only. Multi-period tail distribution, residual calibration, and Bayesian work are not evaluated.\n",
        encoding="utf-8",
    )
    required_paths.append(run_summary_path)
    for path in required_paths:
        write_artifact_metadata(path, root=ROOT, run_id=RUN_ID, stage="R3", input_artifacts=[panel_path, r2_summary],
                                raw_manifest=ROOT / "data/manifests/ffiec_manifest.csv",
                                field_mapping=ROOT / "metadata/field_mapping.csv", validation_status=summary["validation_status"],
                                model_spec=ROOT / "configs/model_specs.yaml")
    print(json.dumps(summary))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
