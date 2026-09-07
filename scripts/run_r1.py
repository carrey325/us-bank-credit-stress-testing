"""Rebuild and validate the R1 standard layer, credit panel, and QA outputs."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.artifacts import R1_DEFINITION_VERSION, sha256_file, write_artifact_metadata
from bankstress.config import load_config
from bankstress.qa.report import write_qa
from bankstress.transform.panel import build_credit_panel
from bankstress.transform.standardize import standardize_archives


RUN_ID = "r1-20260907T121900Z"
BASE = ROOT / "tmp" / "r1_baseline_09e036b"
OUT = ROOT / "outputs" / "repair" / "r1"


def verify_raw_manifest(config: dict) -> pd.DataFrame:
    manifest = pd.read_csv(config["paths"]["manifest"])
    rows = []
    for row in manifest.itertuples(index=False):
        path = config["paths"]["raw_ffiec"] / row.file_name
        actual = sha256_file(path) if path.exists() else None
        rows.append({"report_period": row.report_period, "file_name": row.file_name, "expected_sha256": row.sha256,
                     "actual_sha256": actual, "hash_match": actual == row.sha256, "size_bytes": path.stat().st_size if path.exists() else None})
    result = pd.DataFrame(rows)
    if len(result) != 84 or not result["hash_match"].all():
        raise RuntimeError("Raw FFIEC snapshot is incomplete or differs from the retained manifest")
    return result


def write_change_outputs(old: pd.DataFrame, new: pd.DataFrame) -> None:
    keys = ["bank_id", "report_date", "segment"]
    fields = ["exposure", "annualized_nco_rate", "cre_share", "cre_to_tier1", "eligible_for_model"]
    comparison = old[keys + fields].merge(new[keys + fields + ["form", "exposure_status", "flow_complete", "scope_match", "mapping_id", "reason"]],
        on=keys, how="outer", suffixes=("_old", "_new"), indicator=True)
    comparison["sample_change"] = comparison["_merge"].map({"both":"COMMON", "left_only":"EXITED", "right_only":"NEW"})
    for field in ["exposure", "annualized_nco_rate", "cre_share", "cre_to_tier1"]:
        comparison[f"{field}_change"] = comparison[f"{field}_new"] - comparison[f"{field}_old"]
    comparison.groupby(["sample_change", "form", "segment"], observed=True, dropna=False).agg(
        observations=("bank_id", "size"), banks=("bank_id", "nunique"), first_date=("report_date", "min"), last_date=("report_date", "max"),
        exposure_old_mean=("exposure_old", "mean"), exposure_new_mean=("exposure_new", "mean"), exposure_mean_change=("exposure_change", "mean"),
        annualized_nco_rate_old_mean=("annualized_nco_rate_old", "mean"), annualized_nco_rate_new_mean=("annualized_nco_rate_new", "mean"),
        annualized_nco_rate_mean_change=("annualized_nco_rate_change", "mean"), cre_share_mean_change=("cre_share_change", "mean"),
        cre_to_tier1_mean_change=("cre_to_tier1_change", "mean"), eligible_old=("eligible_for_model_old", "sum"), eligible_new=("eligible_for_model_new", "sum"),
    ).reset_index().to_csv(OUT / "panel_change_summary.csv", index=False)
    date = pd.to_datetime(new["report_date"])
    coverage = new.assign(period_bucket=pd.cut(date.dt.year, [2004, 2007, 2012, 2019, 2025], labels=["2005-2007", "2008-2012", "2013-2019", "2020-2025"]))
    coverage.groupby(["form", "period_bucket", "segment"], observed=True, dropna=False).agg(
        observations=("bank_id", "size"), exposure_complete=("exposure_complete", "sum"),
        flow_complete=("flow_complete", "sum"), scope_match=("scope_match", "sum"),
        usable_rate=("annualized_nco_rate", lambda x: int(x.notna().sum())),
        eligible=("eligible_for_model", "sum"), reported_zero=("exposure_status", lambda x: int(x.eq("REPORTED_ZERO").sum())),
        missing_required=("exposure_status", lambda x: int(x.eq("MISSING_REQUIRED").sum())),
        not_applicable=("exposure_status", lambda x: int(x.eq("NOT_APPLICABLE").sum())),
    ).reset_index().to_csv(OUT / "coverage_by_form_period.csv", index=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config(ROOT)
    inputs = verify_raw_manifest(config)
    inputs.to_csv(OUT / "input_manifest_check.csv", index=False)
    institutions = pd.read_csv(config["paths"]["metadata"] / "institutions.csv", dtype={"bank_id": str, "cert": str})
    lineage = pd.read_csv(config["paths"]["metadata"] / "institution_lineage.csv", dtype={"bank_id": str})
    mapping_path = config["paths"]["metadata"] / "field_mapping.csv"
    standard = standardize_archives(config["paths"]["raw_ffiec"], mapping_path, config["paths"]["standard"], set(institutions.bank_id))
    core_institutions = institutions.loc[institutions["core_sample_flag"].eq(1)].copy()
    core_standard = standard.loc[standard["bank_id"].isin(set(core_institutions["bank_id"]))].copy()
    panel = build_credit_panel(core_standard, core_institutions, config, lineage)
    panel.to_parquet(config["paths"]["derived"], index=False)
    exceptions_path = config["paths"]["metadata"] / "nco_reconciliation_exceptions.csv"
    recon, audit = write_qa(core_standard, panel, pd.read_csv(mapping_path), config["paths"]["qa"], pd.read_csv(exceptions_path))
    old = pd.read_parquet(BASE / "credit_panel.parquet")
    write_change_outputs(old, panel)

    structural = {
        "raw_manifest_rows": len(inputs), "raw_hash_failures": int((~inputs.hash_match).sum()),
        "standard_rows": len(standard), "panel_rows": len(panel), "banks": int(panel.bank_id.nunique()),
        "duplicate_standard_keys": int(standard.duplicated(["bank_id", "report_date", "raw_code"]).sum()),
        "partial_exposure_values_emitted": int((panel["exposure_complete"].eq(0) & panel["exposure"].notna()).sum()),
        "scope_mismatch_rates_emitted": int((~panel["scope_match"] & panel["annualized_nco_rate"].notna()).sum()),
        "negative_nco_retained": int(panel["segment_nco"].lt(0).sum()),
        "nco_reconciliation_review_required": int(recon["nco_reconciliation_status"].eq("REVIEW_REQUIRED").sum()),
        "capital_reconciliation_failures": int(recon["capital_reconciliation_status"].eq("FAIL_OUTSIDE_TOLERANCE").sum()),
        "formula_audit_failures": int(audit["pass_fail"].eq("fail").sum()),
    }
    source_audit_path = ROOT / "metadata" / "manual_source_audit.csv"
    source_audit = pd.read_csv(source_audit_path) if source_audit_path.exists() else pd.DataFrame()
    structural["source_audit_rows"] = len(source_audit)
    structural["source_audit_failures"] = int(source_audit["reviewer_conclusion"].ne("PASS").sum()) if len(source_audit) else None
    pass_checks = (structural["raw_hash_failures"] == 0 and structural["duplicate_standard_keys"] == 0
                   and structural["partial_exposure_values_emitted"] == 0 and structural["scope_mismatch_rates_emitted"] == 0
                   and structural["formula_audit_failures"] == 0 and structural["source_audit_rows"] >= 100
                   and structural["source_audit_failures"] == 0)
    summary = {"run_id": RUN_ID, "stage": "R1", "data_definition_version": R1_DEFINITION_VERSION,
               "created_at": datetime.now(timezone.utc).isoformat(), "validation_status": "PASS" if pass_checks else "FAIL",
               "checks": structural,
               "limitations": ["FFIEC 031 CRE and Mortgage exposure rates before 2013Q2 are unavailable because retained inputs lack a verified consolidated detailed stock mapping.",
                               "Total NPL remains a bank-level nonaccrual fallback, not a segment NPL measure.",
                               "Model, tail, stress, and reporting artifacts remain INVALID_PENDING_REBUILD."]}
    summary_path = OUT / "validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    status = summary["validation_status"]
    common_inputs = [config["paths"]["manifest"], mapping_path]
    write_artifact_metadata(config["paths"]["standard"], root=ROOT, run_id=RUN_ID, stage="R1", input_artifacts=common_inputs,
                            raw_manifest=config["paths"]["manifest"], field_mapping=mapping_path, validation_status=status)
    write_artifact_metadata(config["paths"]["derived"], root=ROOT, run_id=RUN_ID, stage="R1", input_artifacts=[config["paths"]["standard"], *common_inputs],
                            raw_manifest=config["paths"]["manifest"], field_mapping=mapping_path, validation_status=status)
    write_artifact_metadata(summary_path, root=ROOT, run_id=RUN_ID, stage="R1", input_artifacts=[config["paths"]["derived"], *common_inputs],
                            raw_manifest=config["paths"]["manifest"], field_mapping=mapping_path, validation_status=status)
    for artifact in [OUT / "input_manifest_check.csv", OUT / "panel_change_summary.csv", OUT / "coverage_by_form_period.csv",
                     OUT / "definition_audit.md", config["paths"]["qa"] / "reconciliation_summary.csv",
                     config["paths"]["qa"] / "data_quality_report.md"]:
        write_artifact_metadata(artifact, root=ROOT, run_id=RUN_ID, stage="R1", input_artifacts=[config["paths"]["derived"], *common_inputs],
                                raw_manifest=config["paths"]["manifest"], field_mapping=mapping_path, validation_status=status)
    print(json.dumps(summary, indent=2))
    if not pass_checks:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
