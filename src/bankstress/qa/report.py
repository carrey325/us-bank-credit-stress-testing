from __future__ import annotations

from pathlib import Path
import pandas as pd


def write_qa(standard: pd.DataFrame, panel: pd.DataFrame, mapping: pd.DataFrame, qa_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    qa_dir.mkdir(parents=True, exist_ok=True)
    controls = panel.groupby(["bank_id", "report_date"], as_index=False).agg(total_loans=("total_loans", "first"), total_charge_off=("total_charge_off", "first"), total_recovery=("total_recovery", "first"), tier1_capital=("tier1_capital", "first"), total_assets=("total_assets", "first"))
    exposure = panel.groupby(["bank_id", "report_date"], as_index=False).agg(mapped_exposure=("exposure", "sum"), mapped_nco=("segment_nco", "sum"))
    recon = controls.merge(exposure, on=["bank_id", "report_date"], how="left")
    recon["covered_share_of_total_loans"] = recon["mapped_exposure"] / recon["total_loans"].where(recon["total_loans"] > 0)
    recon["reported_total_nco"] = recon["total_charge_off"] - recon["total_recovery"]
    recon["mapped_minus_reported_nco"] = recon["mapped_nco"] - recon["reported_total_nco"]
    recon["capital_ratio_proxy"] = recon["tier1_capital"] / recon["total_assets"].where(recon["total_assets"] > 0)
    recon.to_csv(qa_dir / "reconciliation_summary.csv", index=False)
    audit = panel.dropna(subset=["charge_off", "recovery", "segment_nco"]).sample(min(200, panel.dropna(subset=["charge_off", "recovery", "segment_nco"]).shape[0]), random_state=772).copy()
    audit = audit.assign(raw_field="charge_off,recovery", raw_value=audit["charge_off"].astype(str) + "," + audit["recovery"].astype(str), formula="quarterly_nco = quarterly_charge_off - quarterly_recovery", derived_value=audit["segment_nco"], pass_fail=(audit["segment_nco"].round(8).eq((audit["charge_off"] - audit["recovery"]).round(8))).map({True: "pass", False: "fail"}), reviewer_note="Deterministic formula trace; human source-document review remains required.")
    audit[["bank_id", "report_date", "segment", "raw_field", "raw_value", "formula", "derived_value", "pass_fail", "reviewer_note"]].to_csv(qa_dir / "manual_audit.csv", index=False)
    expected_dates = ["2005-03-31", "2010-03-31", "2020-03-31", "2025-12-31"]
    present = standard.assign(report_date=standard.report_date.astype(str)).groupby("report_date").raw_code.nunique()
    mapping_validation = {date: int(present.get(date, 0)) for date in expected_dates}
    report = "\n".join([
        "# Batch 1 data-quality report", "", f"- Standard observations: {len(standard):,}", f"- Derived observations: {len(panel):,}", f"- Core banks: {panel.bank_id.nunique():,}", f"- Field-mapping rows: {len(mapping):,}", f"- Duplicate standard bank/date/raw-code keys: {int(standard.duplicated(['bank_id','report_date','raw_code']).sum())}", f"- Negative NCO observations retained: {int((panel.segment_nco < 0).sum())}", f"- FDIC merger quarters flagged: {int(panel.merger_quarter_flag.sum())}", f"- Asset-jump quarters flagged: {int(panel.asset_jump_flag.sum())}", f"- Manual formula-audit failures: {int((audit.pass_fail == 'fail').sum())}", "", "## Mapped raw-field presence", "", *[f"- {date}: {count} mapped raw codes" for date, count in mapping_validation.items()], "", "## Limitations", "", "- The historical Call Report taxonomy has genuine reporting-detail changes. Missing segment detail remains missing; it is never filled with zero.", "- `tier1_capital` is a conservative RC proxy pending Batch 2's capital-model interface; the reconciliation file labels it as a proxy rather than a reported Tier 1 ratio.", "- FDIC history events are branch-granular and collapsed to bank-quarter merger flags; no virtual-bank reconstruction is claimed.", "- The deterministic audit validates formulas and traces, not a human review of 100 source facsimiles.", ""
    ])
    (qa_dir / "data_quality_report.md").write_text(report, encoding="utf-8")
    return recon, audit
