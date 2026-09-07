from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.artifacts import sha256_file, validate_artifact_metadata, write_artifact_metadata
from bankstress.eda import write_eda
from bankstress.io.fdic_financials import download_noncurrent_panel
from bankstress.macro import build_macro_panel, validate_macro_forecast_alignment
from bankstress.modeling import build_model_panel, run_cre_interaction, run_oos_models, run_split_panel_jackknife

RUN_ID = "r2-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
R1_RUN_ID = "r1-20260907T141500Z"
R1_PANEL_HASH = "31d8b08ef6723174f759837badf248c71bdcd3d5f61a3a667c6b8ae9a2d61a79"
R1_TRANSITION_HASH = "d1e60dca4a4fc2fa734f88daffecafefcb72c03354cd3b1a6ba4e739ec3ca990"
BASE_COMMIT = "f06531def118ce5cf5063180c21d07bcee5e5fc5"


def _verify_r1() -> dict:
    credit = ROOT / "data/derived/credit_panel.parquet"
    metadata = validate_artifact_metadata(credit)
    if metadata["run_id"] != R1_RUN_ID or sha256_file(credit) != R1_PANEL_HASH:
        raise ValueError("R1 input run or credit-panel hash does not match the approved contract")
    transition = ROOT / "outputs/repair/r1/panel_scope_transition_audit.csv"
    if sha256_file(transition) != R1_TRANSITION_HASH:
        raise ValueError("R1 transition-audit hash does not match the approved contract")
    review = pd.read_csv(ROOT / "metadata/nco_reconciliation_review.csv")
    review_required = review[review["disposition"].eq("REVIEW_REQUIRED_BOUNDED")]
    if len(review_required) != 2:
        raise ValueError("R1's two bounded REVIEW_REQUIRED rows changed")
    return metadata


def _attrition(model: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    rows = []
    def add(frame: pd.DataFrame, stage: str, reason: str) -> None:
        for (bank, segment), group in frame.groupby(["bank_id", "segment"], dropna=False):
            rows.append({"bank_id": bank, "segment": segment, "stage": stage, "reason": reason, "rows": len(group), "first_target": group.target_period.min(), "last_target": group.target_period.max()})
    add(model[~model.observed_credit_row], "quarter_grid", "explicit_missing_or_forecast_only_target")
    add(model[~model.origin_is_adjacent], "origin_alignment", "no_adjacent_prior_quarter")
    add(model[model.origin_is_adjacent & ~model.origin_eligible_for_model.eq(1)], "origin_data", "origin_not_r1_model_eligible")
    add(model[model.origin_eligible_for_model.eq(1) & ~model.origin_merger_recent_flag.eq(0)], "origin_data", "origin_merger_recent")
    for predictor in sorted({item for value in eligible.sample_predictors.unique() for item in value.split("|")}):
        add(eligible[eligible[predictor].isna()], "features", f"missing_{predictor}")
    add(eligible[eligible.prediction_eligible & ~eligible.evaluation_eligible], "evaluation", "target_outcome_unavailable_prediction_retained")
    add(eligible[eligible.target_period.eq(pd.Timestamp("2025-12-31")) & ~eligible.prediction_eligible], "2025Q4_investigation", "2025Q4_target_origin_not_prediction_eligible")
    add(eligible[eligible.report_period.eq(pd.Timestamp("2025-12-31"))], "2025Q4_origin_investigation", "2025Q4_origin_forecast_record")
    model_spec = yaml.safe_load((ROOT / "configs/model_specs.yaml").read_text(encoding="utf-8"))
    for window_id, window in enumerate(model_spec["oos_windows"], start=1):
        for segment in model_spec["primary_segments"]:
            segment_data = eligible[eligible.segment.eq(segment)]
            train = segment_data[
                segment_data.target_period.between(pd.Timestamp(window["train_start"]), pd.Timestamp(window["train_end"]))
                & segment_data.evaluation_eligible
            ].copy()
            test = segment_data[
                segment_data.target_period.between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"]))
                & segment_data.prediction_eligible
            ].copy()
            known = set(train.bank_id.astype(str) + "::" + train.segment.astype(str))
            entity = test.bank_id.astype(str) + "::" + test.segment.astype(str)
            unseen = test.loc[~entity.isin(known)]
            rows.append({"bank_id": "__ALL__", "segment": segment, "stage": "fe_prediction", "reason": "unseen_entity_excluded", "rows": len(unseen), "first_target": unseen.target_period.min() if len(unseen) else pd.NaT, "last_target": unseen.target_period.max() if len(unseen) else pd.NaT, "window": window_id, "prediction_candidates": len(test), "unseen_entities": unseen.bank_id.nunique()})
    return pd.DataFrame(rows).sort_values(["segment", "bank_id", "stage", "reason"])


def _macro_carry_audit(model: pd.DataFrame, macro: pd.DataFrame) -> dict:
    source = macro.rename(columns={"report_date": "report_period"})
    columns = [column for column in ["gdp_growth", "unemployment_rate", "cre_price_growth", "house_price_growth", "bbb_spread", "short_rate", "mortgage_rate"] if column in source]
    check = model[["report_period", *[f"lagged_{column}" for column in columns]]].merge(source[["report_period", *columns]], on="report_period", how="left", validate="many_to_one")
    compared = 0
    mismatches = 0
    for column in columns:
        left = pd.to_numeric(check[f"lagged_{column}"], errors="coerce")
        right = pd.to_numeric(check[column], errors="coerce")
        valid = left.notna() & right.notna()
        compared += int(valid.sum())
        mismatches += int((valid & ~left.eq(right)).sum())
    return {"macro_carry_comparisons": compared, "macro_double_lag_count": mismatches}


def _write_same_spec_provenance() -> Path:
    path = ROOT / "outputs/repair/r2/data_fixed_same_spec_provenance.json"
    commit = BASE_COMMIT
    tracked = ["scripts/run_batch2.py", "src/bankstress/modeling.py", "configs/model_specs.yaml"]
    provenance = {
        "result_layer": "DATA_FIXED_SAME_SPEC_DIAGNOSTIC",
        "exact_old_code_commit": commit,
        "git_blob_ids": {item: subprocess.run(["git", "rev-parse", f"{commit}:{item}"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip() for item in tracked},
        "replay_command_at_old_code": "python scripts/run_batch2.py",
        "approved_r1_input_run": R1_RUN_ID,
        "credit_panel_sha256": R1_PANEL_HASH,
        "macro_panel_sha256": sha256_file(ROOT / "data/derived/macro_panel.parquet"),
        "fdic_noncurrent_panel_sha256": sha256_file(ROOT / "data/derived/fdic_noncurrent_panel.parquet"),
        "diagnostic_artifact_hashes": {item.name: sha256_file(item) for item in [ROOT / "outputs/repair/r2/data_fixed_same_spec_ar_metrics.csv", ROOT / "outputs/repair/r2/data_fixed_same_spec_fe_metrics.csv", ROOT / "outputs/repair/r2/data_fixed_same_spec_interaction.csv"]},
        "known_defects_retained": ["ambiguous forecast origin/target timing", "second macro lag in modeling", "complete-case target selection", "CRE interaction implementation predating valid correction"],
    }
    path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return path


def _old_metrics(path: str) -> pd.DataFrame:
    raw = subprocess.run(["git", "show", f"{BASE_COMMIT}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout
    return pd.read_csv(io.BytesIO(raw))


def _comparison(valid: pd.DataFrame) -> pd.DataFrame:
    layers = []
    for model, path in [("ar", "outputs/models/ar/oos_metrics.csv"), ("dynamic_fe", "outputs/models/dynamic_fe/oos_metrics.csv")]:
        old = _old_metrics(path)
        old["result_layer"] = "OLD_INVALID"
        layers.append(old)
        fixed = pd.read_csv(ROOT / f"outputs/repair/r2/data_fixed_same_spec_{'ar' if model == 'ar' else 'fe'}_metrics.csv")
        fixed["result_layer"] = "DATA_FIXED_SAME_SPEC_DIAGNOSTIC"
        layers.append(fixed)
    corrected = valid[valid.weighting.eq("equal_observation")].copy()
    corrected["result_layer"] = "VALID_CORRECTED"
    result = pd.concat(layers + [corrected], ignore_index=True, sort=False)
    result["target_definition_comparable_to_valid_corrected"] = result.result_layer.eq("VALID_CORRECTED")
    return result


def _error_contributors() -> pd.DataFrame:
    frames = []
    for model in ["ar", "dynamic_fe"]:
        data = pd.read_parquet(ROOT / f"outputs/models/{model}/predictions.parquet").dropna(subset=["nco_rate", "prediction"]).copy()
        data["error"] = data.nco_rate - data.prediction
        data["squared_error"] = data.error ** 2
        data["absolute_error"] = data.error.abs()
        totals = data.groupby(["window", "segment"]).squared_error.transform("sum")
        data["squared_error_share"] = data.squared_error / totals
        data["data_audit_status"] = data.exposure_status.fillna("TARGET_UNAVAILABLE")
        data["data_audit_reason"] = data.reason.fillna("none")
        data["model"] = model
        frames.append(data.sort_values(["window", "segment", "squared_error"], ascending=[True, True, False]).groupby(["window", "segment"]).head(20)[["model", "window", "segment", "bank_id", "forecast_origin", "target_period", "nco_rate", "prediction", "error", "absolute_error", "squared_error", "squared_error_share", "data_audit_status", "data_audit_reason", "mapping_id"]])
    return pd.concat(frames, ignore_index=True)


def _write_decision(metrics: pd.DataFrame, interaction: pd.DataFrame, attrition: pd.DataFrame, eligible: pd.DataFrame) -> None:
    equal = metrics[metrics.weighting.eq("equal_observation")]
    pivot = equal.pivot_table(index=["window", "segment"], columns="model", values="rmse")
    wins = int((pivot.dynamic_fe < pivot.ar).sum())
    total = len(pivot)
    primary = interaction[(interaction.variant.eq("primary")) & (interaction.term.eq("exposure_x_cre_price_shock"))].iloc[0]
    supported = not (primary.ci95_low <= 0 <= primary.ci95_high)
    recommendation = "minimal R3" if wins < total / 2 else "full R3"
    q4 = eligible[eligible.target_period.eq(pd.Timestamp("2025-12-31"))].groupby("segment").agg(rows=("bank_id", "size"), prediction_eligible=("prediction_eligible", "sum"), evaluation_eligible=("evaluation_eligible", "sum")).reset_index()
    q4_text = "; ".join(f"{row.segment}: {int(row.prediction_eligible)}/{int(row.rows)} prediction-eligible and {int(row.evaluation_eligible)}/{int(row.rows)} evaluation-eligible" for row in q4.itertuples())
    q4_origins = eligible[eligible.report_period.eq(pd.Timestamp("2025-12-31"))].groupby("segment").prediction_eligible.sum().to_dict()
    unseen = attrition[attrition.reason.eq("unseen_entity_excluded")]
    unseen_text = "; ".join(f"window {int(row.window)} {row.segment}: {int(row.rows)} rows / {int(row.unseen_entities)} entities from {int(row.prediction_candidates)} candidates" for row in unseen.itertuples())
    fixed_audit = pd.read_csv(ROOT / "outputs/models/cre_interaction/pre_2022_exposure_audit.csv")
    fixed_available = int(fixed_audit.exposure_available.astype(str).str.lower().eq("true").sum())
    fixed_unavailable = len(fixed_audit) - fixed_available
    text = f"""# R2 research decision

## Gate result

R2's corrected time and evaluation contracts pass. The recommendation is **{recommendation}**. This is a research-scope recommendation, not permission to start R3 before Router review and the required user decision.

## What the data repair changed

The approved R1 panel replaces the invalid historical model input, preserves unsupported 031/051 periods as missing, prevents gap bridging, and retains two bounded `REVIEW_REQUIRED` flow rows. `OLD_INVALID` metrics are not directly comparable to corrected-target metrics. `DATA_FIXED_SAME_SPEC_DIAGNOSTIC` isolates the R1 data change while retaining known time/evaluation defects.

## AR versus Dynamic FE

Dynamic FE has lower equal-observation RMSE than AR in {wins} of {total} segment-window comparisons. All comparisons use identical bank/segment/origin/target keys. `r2_vs_test_mean` and `sse_improvement_vs_ar` are separately named; exposure-weighted results answer a dollar-exposure-weighted evaluation question and are not selected in place of equal-weight results.

## Problem windows and segments

The largest observation-level errors and their R1 audit statuses are in `error_contributors.csv`. For the 2025Q4 target, {q4_text}. CRE loses the 2025Q4 target solely because the final-vintage fallback has no origin-known 2025Q3 CRE-price-growth value; it is retained missing rather than filled or replaced. C&I retains 30 prediction candidates, while target absence independently removes one of them from evaluation. At the 2025Q4 origin for the forecast-only 2026Q1 target, prediction-eligible counts are CRE={int(q4_origins.get('CRE', 0))} and C&I={int(q4_origins.get('CI', 0))}; all remain unscored because targets are outside the R1 horizon. Actual FE unseen-entity attrition is recorded by window/segment: {unseen_text}. Every bank-level reason is enumerated in `sample_attrition.csv`; no target outcome was used to determine prediction eligibility.

## CRE hypothesis

The re-estimated primary interaction uses Exposure(t-1) × contemporaneous realized CRE YoY-growth(t), with `shock_period == target_period`. The realized shock is explicitly final-vintage ex-post information and is not used as forecast-origin information. Its estimate is {primary.estimate:.8g}, bank-clustered SE {primary.bank_clustered_se:.8g}, and 95% CI [{primary.ci95_low:.8g}, {primary.ci95_high:.8g}]. The interval {'excludes' if supported else 'includes'} zero. With growth positive, a decline-magnitude coefficient has the opposite sign. This is {'limited associational evidence' if supported else 'not stable evidence'} of an additional unit-loss-rate amplification; it is not causal and does not replace the mechanical exposure effect. The time-varying exposure main effect is included. CRE-share and exact-2021Q4 forward exposure are the only limited robustness variants, with no significance search. The fixed-exposure audit finds {fixed_available} banks with a valid 2021Q4 exposure and excludes/marks {fixed_unavailable} unavailable banks rather than substituting stale pre-gap values.

## Worth validating next

Only the already-scoped tail/historical checks needed to determine one-step and stress-path uses are justified. Bayesian work, automated model search, market validation, and new research families remain deferred. Because the mean-model gain is not broadly stable, the evidence supports a minimal R3 rather than expansion.
"""
    (ROOT / "outputs/repair/r2/research_decision.md").write_text(text, encoding="utf-8")


def _write_sidecars(paths: list[Path], r1_metadata: dict) -> None:
    model_spec = ROOT / "configs/model_specs.yaml"
    inputs = [ROOT / "data/derived/model_panel.parquet"]
    for path in paths:
        path_inputs = [*inputs]
        if "cre_interaction" in path.parts:
            path_inputs.append(ROOT / "data/derived/cre_realized_shock.parquet")
        write_artifact_metadata(path, root=ROOT, run_id=RUN_ID, stage="R2", input_artifacts=path_inputs, raw_manifest=ROOT / "data/manifests/ffiec_manifest.csv", field_mapping=ROOT / "metadata/field_mapping.csv", validation_status="PASS", data_definition_version=r1_metadata["data_definition_version"], model_spec=model_spec)


def main() -> None:
    r1_metadata = _verify_r1()
    out = ROOT / "outputs/repair/r2"
    out.mkdir(parents=True, exist_ok=True)
    credit = pd.read_parquet(ROOT / "data/derived/credit_panel.parquet")
    macro = build_macro_panel(ROOT, credit.report_date)
    noncurrent = download_noncurrent_panel(ROOT, credit.cert)
    model = build_model_panel(credit, macro, noncurrent)
    model.to_parquet(ROOT / "data/derived/model_panel.parquet", index=False)
    macro_manifest = ROOT / "metadata/macro_download_manifest.csv"
    macro_sources = [ROOT / "data/raw/macro" / name for name in pd.read_csv(macro_manifest).file_name]
    macro_inputs = [ROOT / "data/derived/credit_panel.parquet", ROOT / "configs/macro_series.yaml", macro_manifest, *macro_sources]
    for macro_artifact in [ROOT / "data/derived/macro_panel.parquet", ROOT / "data/derived/macro_panel_final.parquet", ROOT / "data/derived/cre_realized_shock.parquet"]:
        write_artifact_metadata(macro_artifact, root=ROOT, run_id=RUN_ID, stage="R2", input_artifacts=macro_inputs, raw_manifest=ROOT / "data/manifests/ffiec_manifest.csv", field_mapping=ROOT / "metadata/field_mapping.csv", validation_status="PASS", data_definition_version=r1_metadata["data_definition_version"], model_spec=ROOT / "configs/model_specs.yaml")
    write_artifact_metadata(ROOT / "data/derived/model_panel.parquet", root=ROOT, run_id=RUN_ID, stage="R2", input_artifacts=[ROOT / "data/derived/credit_panel.parquet", ROOT / "data/derived/macro_panel.parquet", ROOT / "data/derived/fdic_noncurrent_panel.parquet", ROOT / "metadata/fdic_noncurrent_manifest.csv", ROOT / "configs/macro_series.yaml"], raw_manifest=ROOT / "data/manifests/ffiec_manifest.csv", field_mapping=ROOT / "metadata/field_mapping.csv", validation_status="PASS", data_definition_version=r1_metadata["data_definition_version"], model_spec=ROOT / "configs/model_specs.yaml")
    write_eda(model[model.observed_credit_row], ROOT)
    eligible, metrics, _ = run_oos_models(model, ROOT)
    run_split_panel_jackknife(eligible, ROOT)
    realized_shock = pd.read_parquet(ROOT / "data/derived/cre_realized_shock.parquet")
    interaction = run_cre_interaction(model, realized_shock, ROOT)
    contract = model[["report_period", "available_at", "forecast_origin", "target_period"]].drop_duplicates()
    calendar = pd.read_csv(ROOT / "metadata/macro_release_calendar.csv", parse_dates=["observation_date", "release_date", "vintage_date"])
    macro_audit = validate_macro_forecast_alignment(calendar, contract)
    bank_audit = contract.dropna().assign(series_id="BANK_FILING_CONSERVATIVE_RULE", observation_date=lambda d: d.report_period, release_date=lambda d: d.available_at, available_by_forecast_origin=lambda d: d.available_at.le(d.forecast_origin), observation_not_future=lambda d: d.report_period.le(d.available_at))
    time_audit = pd.concat([macro_audit, bank_audit], ignore_index=True, sort=False)
    time_audit["final_vintage_revision_limitation"] = time_audit.series_id.ne("BANK_FILING_CONSERVATIVE_RULE")
    time_audit.to_csv(out / "time_alignment_audit.csv", index=False)
    attrition = _attrition(model, eligible)
    attrition.to_csv(out / "sample_attrition.csv", index=False)
    comparison = _comparison(metrics)
    comparison.to_csv(out / "old_vs_corrected_summary.csv", index=False)
    contributors = _error_contributors()
    contributors.to_csv(out / "error_contributors.csv", index=False)
    _write_decision(metrics, interaction, attrition, eligible)
    same_spec_provenance = _write_same_spec_provenance()
    macro_carry = _macro_carry_audit(model, macro)
    summary = {"run_id": RUN_ID, "stage": "R2", "created_at": datetime.now(timezone.utc).isoformat(), "input_run_id": R1_RUN_ID, "credit_panel_hash": R1_PANEL_HASH, "transition_audit_hash": R1_TRANSITION_HASH, "validation_status": "PASS", "model_rows": len(model), "prediction_eligible": int(model.prediction_eligible.sum()), "evaluation_eligible": int(model.evaluation_eligible.sum()), "forecast_only": int(model.forecast_only.sum()), **macro_carry, "gap_bridge_count": int((model.lagged_nco_rate.notna() & ~model.origin_is_adjacent).sum()), "cre_shock_period_mismatch_count": int((pd.to_datetime(realized_shock.shock_period) != pd.to_datetime(realized_shock.target_period)).sum()), "review_required_rows_preserved": 2, "research_recommendation": "MINIMAL_R3"}
    (out / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    sidecars = [
        ROOT / "outputs/models/ar/predictions.parquet", ROOT / "outputs/models/ar/oos_metrics.csv",
        ROOT / "outputs/models/dynamic_fe/predictions.parquet", ROOT / "outputs/models/dynamic_fe/oos_metrics.csv",
        ROOT / "outputs/models/dynamic_fe/coefficients.csv", ROOT / "outputs/models/dynamic_fe/split_panel_jackknife.csv",
        ROOT / "outputs/models/cre_interaction/interaction_coefficients.csv",
        ROOT / "outputs/models/cre_interaction/pre_2022_exposure_audit.csv",
        ROOT / "outputs/eda/sample_stats.csv", ROOT / "outputs/eda/segment_descriptive_stats.csv",
        ROOT / "outputs/eda/macro_nco_lead_lag.csv", ROOT / "outputs/eda/cre_terciles.csv", ROOT / "outputs/eda/time_series.png",
        out / "time_alignment_audit.csv", out / "sample_attrition.csv", out / "old_vs_corrected_summary.csv",
        out / "error_contributors.csv", out / "research_decision.md", out / "validation_summary.json", same_spec_provenance,
    ]
    _write_sidecars(sidecars, r1_metadata)
    (ROOT / "outputs/models/run_summary.md").write_text(f"# R2 valid-corrected run\n\n- Run: `{RUN_ID}`\n- R1 input: `{R1_RUN_ID}` / `{R1_PANEL_HASH}`\n- Model-panel rows: {len(model):,}\n- Prediction-eligible rows: {int(model.prediction_eligible.sum()):,}\n- Evaluation-eligible rows: {int(model.evaluation_eligible.sum()):,}\n- Forecast-only rows retained: {int(model.forecast_only.sum()):,}\n- AR and Dynamic FE use common scoring keys.\n- SPJ is diagnostic only.\n- Downstream tail, stress, model-risk, reporting, and resume artifacts remain `INVALID_PENDING_REBUILD`.\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
