"""Export a compact, traceable research snapshot from existing analytical outputs.

This copies recorded evidence and computes summaries; it does not refit models.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "sample.csv": "outputs/eda/sample_stats.csv",
    "mean_model_comparison.csv": "outputs/reporting/tables/model_comparison.csv",
    "tail_metrics.csv": "outputs/validation/tail_metrics.csv",
    "stress_by_bank.csv": "outputs/stress/conditional_mean_summary.csv",
    "stress_results.csv": "outputs/reporting/tables/fed_stress_results.csv",
    "cre_interaction.csv": "outputs/models/cre_interaction/interaction_coefficients.csv",
    "cre_price_shock.csv": "outputs/repair/r2/cre_realized_shock_audit.csv",
    "bayesian_diagnostics.csv": "outputs/models/bayesian/diagnostics.csv",
    "validation.json": "outputs/repair/r3/validation_summary.json",
    "reproducibility.json": "outputs/reporting/reproducibility_audit.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(evidence: Path, mapping: Path) -> dict:
    sample = pd.read_csv(evidence / "sample.csv").iloc[0]
    means = pd.read_csv(evidence / "mean_model_comparison.csv")
    paired = means.pivot(index=["window", "segment"], columns="model", values="rmse")
    tails = pd.read_csv(evidence / "tail_metrics.csv")
    tails = tails[tails.prediction_version.eq("POST_REARRANGEMENT") & tails.tau.eq(0.9)]
    # Common bank/segment/origin/target scoring keys are checked by the estimator.
    if not tails.common_scoring_keys_verified.all():
        raise ValueError("Tail comparison does not have verified common scoring keys")
    tail = tails.pivot(index=["window", "segment"], columns="model_family", values="pinball_loss")
    tail["improvement_pct"] = 100 * (1 - tail.dynamic_quantile / tail.ar_quantile)
    stress = pd.read_csv(evidence / "stress_by_bank.csv")
    stress = stress[stress.scenario.isin(["baseline", "severely_adverse"]) & stress.segment.eq("CI")]
    totals = stress.groupby(["model", "scenario"]).cumulative_loss_thousands.sum()
    validation = json.loads((evidence / "validation.json").read_text())
    return {
        "historical_banks": int(sample.banks),
        "bank_segment_quarters": int(sample.observations),
        "segments": int(sample.segments),
        "quarters": int(sample.quarters),
        "mapped_call_report_codes": int(pd.read_csv(mapping).raw_code.nunique()),
        "stress_banks": int(stress.bank_id.nunique()),
        "stress_quarters": 9,
        "dynamic_fe_rmse_wins": int((paired.dynamic_fe < paired.ar).sum()),
        "mean_comparisons": len(paired),
        "q90_pinball_comparison": tail.reset_index().to_dict(orient="records"),
        "ci_cumulative_loss_usd_billions": [
            {"model": model, "scenario": scenario, "loss": float(value / 1_000_000)}
            for (model, scenario), value in totals.items()
        ],
        "quantile_crossings_before_rearrangement": validation["raw_quantile_crossing_rows"],
        "bayesian_validation": validation["bayesian_status"],
        "five_percent_tail_improvement": "CRE pooled one-step Q90 pinball loss vs AR quantile, after rearrangement; not a cumulative stress-loss metric",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--verify", action="store_true", help="Verify the committed snapshot without raw data")
    args = parser.parse_args()
    output = ROOT / "results"
    evidence = output / "evidence"
    manifest_path = output / "provenance.json"
    if args.verify:
        provenance = json.loads(manifest_path.read_text())
        for row in provenance["files"]:
            if sha256(output / row["file"]) != row["sha256"]:
                raise ValueError(f"Evidence hash mismatch: {row['file']}")
            lineage = row.get("original_lineage")
            if lineage and lineage["artifact_hash"] != row["sha256"]:
                raise ValueError(f"Original lineage hash mismatch: {row['file']}")
        if sha256(ROOT / "metadata/field_mapping.csv") != provenance["field_mapping_sha256"]:
            raise ValueError("Field mapping changed; the snapshot needs review")
        actual = summarize(evidence, ROOT / "metadata/field_mapping.csv")
        if actual != json.loads((output / "summary.json").read_text()):
            raise ValueError("Summary does not match the underlying evidence")
        print(f"Verified {len(provenance['files'])} evidence files and all summary calculations")
        return
    # Preflight all sources before changing an existing snapshot.
    for source in SOURCES.values():
        if not (args.source_root / source).is_file():
            raise FileNotFoundError(f"Missing recorded evidence: {source}")
    evidence.mkdir(parents=True, exist_ok=True)
    files = []
    for name, source in SOURCES.items():
        original = args.source_root / source
        destination = evidence / name
        shutil.copy2(original, destination)
        sidecar = original.with_suffix(original.suffix + ".metadata.json")
        files.append({
            "file": destination.relative_to(output).as_posix(),
            "source_path": source,
            "sha256": sha256(destination),
            "original_lineage": json.loads(sidecar.read_text()) if sidecar.exists() else None,
        })
    source_git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=args.source_root,
                                capture_output=True, text=True)
    provenance = {
        "description": "Recorded analytical evidence; copied without refitting or editing source rows",
        "source_checkout": source_git.stdout.strip() if source_git.returncode == 0 else None,
        "field_mapping_sha256": sha256(ROOT / "metadata/field_mapping.csv"),
        "files": files,
    }
    manifest_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    summary = summarize(evidence, ROOT / "metadata/field_mapping.csv")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
