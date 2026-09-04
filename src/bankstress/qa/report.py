from __future__ import annotations

from pathlib import Path

import pandas as pd

from bankstress.transform.flows import quarterize_ytd


# Call Report monetary values are in thousands. This de minimis allowance covers
# disclosure rounding and coalesced RCON/RCFD variants; it is not an equality
# threshold for the mapped (subset) portfolio.
NCO_GROSS_FLOW_TOLERANCE_THOUSANDS = 50.0


def _flow_reclass_flags(standard: pd.DataFrame) -> pd.DataFrame:
    """Return gross-flow-specific YTD revision flags for causal reconciliation."""
    flows = standard.loc[standard["stock_flow"].eq("flow")].copy()
    if flows.empty:
        return pd.DataFrame(columns=["bank_id", "report_date", "flow_reclass_flag"])
    flows = quarterize_ytd(flows)
    categories = {
        "total_charge_off": "total_charge_off_reclass_flag",
        "total_recovery": "total_recovery_reclass_flag",
        "charge_off": "mapped_charge_off_reclass_flag",
        "recovery": "mapped_recovery_reclass_flag",
    }
    result: pd.DataFrame | None = None
    for metric, column in categories.items():
        subset = flows.loc[flows["standard_metric"].eq(metric)].groupby(["bank_id", "report_date"], as_index=False).agg(
            **{column: ("amendment_or_reclass_flag", "max")}
        )
        result = subset if result is None else result.merge(subset, on=["bank_id", "report_date"], how="outer")
    assert result is not None
    result = result.fillna(0)
    flag_columns = [column for column in categories.values()]
    result[flag_columns] = result[flag_columns].astype(int)
    result["flow_reclass_flag"] = result[flag_columns].max(axis=1)
    return result


def write_qa(standard: pd.DataFrame, panel: pd.DataFrame, mapping: pd.DataFrame, qa_dir: Path, nco_exceptions: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    qa_dir.mkdir(parents=True, exist_ok=True)
    panel = panel.copy()
    for column in ["tier1_capital", "tier1_ratio", "equity_capital", "equity_to_assets_ratio"]:
        if column not in panel:
            panel[column] = pd.NA
    controls = panel.groupby(["bank_id", "report_date"], as_index=False).agg(
        total_loans=("total_loans", "first"), total_charge_off=("total_charge_off", "first"),
        total_recovery=("total_recovery", "first"), tier1_capital=("tier1_capital", "first"), tier1_ratio=("tier1_ratio", "first"),
        equity_capital=("equity_capital", "first"), equity_to_assets_ratio=("equity_to_assets_ratio", "first"), total_assets=("total_assets", "first"),
    )
    mapped = panel.groupby(["bank_id", "report_date"], as_index=False).agg(
        mapped_exposure=("exposure", "sum"), mapped_charge_off=("charge_off", lambda values: values.sum(min_count=1)),
        mapped_recovery=("recovery", lambda values: values.sum(min_count=1)), mapped_nco=("segment_nco", lambda values: values.sum(min_count=1)),
        mapped_segment_count=("segment_nco", lambda values: int(values.notna().sum())),
    )
    recon = controls.merge(mapped, on=["bank_id", "report_date"], how="left")
    if nco_exceptions is not None and not nco_exceptions.empty:
        exceptions = nco_exceptions[["bank_id", "report_date", "exception_type"]].copy()
        exceptions["bank_id"] = exceptions["bank_id"].astype(str)
        exceptions["report_date"] = pd.to_datetime(exceptions["report_date"])
        if exceptions.duplicated(["bank_id", "report_date"]).any():
            raise ValueError("NCO reconciliation exceptions must have unique bank-quarter keys")
        recon = recon.merge(exceptions, on=["bank_id", "report_date"], how="left")
    else:
        recon["exception_type"] = pd.NA
    recon = recon.merge(_flow_reclass_flags(standard), on=["bank_id", "report_date"], how="left")
    reclass_columns = [column for column in recon if column.endswith("_reclass_flag")]
    recon[reclass_columns] = recon[reclass_columns].fillna(0).astype(int)
    recon["covered_share_of_total_loans"] = recon["mapped_exposure"] / recon["total_loans"].where(recon["total_loans"] > 0)
    recon["reported_total_nco"] = recon["total_charge_off"] - recon["total_recovery"]
    recon["mapped_minus_reported_nco"] = recon["mapped_nco"] - recon["reported_total_nco"]
    recon["charge_off_subset_difference"] = recon["mapped_charge_off"] - recon["total_charge_off"]
    recon["recovery_subset_difference"] = recon["mapped_recovery"] - recon["total_recovery"]
    recon["nco_reconciliation_tolerance_thousands"] = NCO_GROSS_FLOW_TOLERANCE_THOUSANDS
    has_controls = recon[["mapped_charge_off", "mapped_recovery", "total_charge_off", "total_recovery"]].notna().all(axis=1)
    charge_off_excess = recon["charge_off_subset_difference"].gt(NCO_GROSS_FLOW_TOLERANCE_THOUSANDS)
    recovery_excess = recon["recovery_subset_difference"].gt(NCO_GROSS_FLOW_TOLERANCE_THOUSANDS)
    gross_subset_pass = ~charge_off_excess & ~recovery_excess
    # A downward revision of a reported *total* flow can explain an excess only
    # in that same gross-flow comparison.  A reclassification in an unrelated
    # component (or a mapped component) does not explain a different mismatch.
    recon["charge_off_ytd_reclass_causally_explains"] = charge_off_excess & recon["total_charge_off_reclass_flag"].eq(1)
    recon["recovery_ytd_reclass_causally_explains"] = recovery_excess & recon["total_recovery_reclass_flag"].eq(1)
    unexplained_excess = (charge_off_excess & ~recon["charge_off_ytd_reclass_causally_explains"]) | (recovery_excess & ~recon["recovery_ytd_reclass_causally_explains"])
    recon["nco_reconciliation_status"] = "NOT_EVALUABLE_MISSING_FLOW"
    recon.loc[has_controls & gross_subset_pass, "nco_reconciliation_status"] = "PASS_SUBSET_GROSS_FLOWS"
    recon.loc[has_controls & ~gross_subset_pass & ~unexplained_excess, "nco_reconciliation_status"] = "EXPLAINED_YTD_RECLASS_GROSS_FLOW"
    recon.loc[has_controls & unexplained_excess, "nco_reconciliation_status"] = "REVIEW_REQUIRED"
    recon.loc[has_controls & recon["exception_type"].notna(), "nco_reconciliation_status"] = "EXPLAINED_SOURCE_FILING_INCONSISTENCY"
    recon.to_csv(qa_dir / "reconciliation_summary.csv", index=False)

    audit_source = panel.dropna(subset=["charge_off", "recovery", "segment_nco"])
    audit = audit_source.sample(min(200, len(audit_source)), random_state=772).copy()
    audit = audit.assign(raw_field="charge_off,recovery", raw_value=audit["charge_off"].astype(str) + "," + audit["recovery"].astype(str), formula="quarterly_nco = quarterly_charge_off - quarterly_recovery", derived_value=audit["segment_nco"], pass_fail=(audit["segment_nco"].round(8).eq((audit["charge_off"] - audit["recovery"]).round(8))).map({True: "pass", False: "fail"}), reviewer_note="Deterministic formula trace; see manual_source_audit.csv for source-document review.")
    audit[["bank_id", "report_date", "segment", "raw_field", "raw_value", "formula", "derived_value", "pass_fail", "reviewer_note"]].to_csv(qa_dir / "manual_audit.csv", index=False)
    expected_dates = ["2005-03-31", "2010-03-31", "2020-03-31", "2025-12-31"]
    present = standard.assign(report_date=standard.report_date.astype(str)).groupby("report_date").raw_code.nunique()
    mapping_validation = {date: int(present.get(date, 0)) for date in expected_dates}
    nco_statuses = recon["nco_reconciliation_status"].value_counts().to_dict()
    review_count = int((recon["nco_reconciliation_status"] == "REVIEW_REQUIRED").sum())
    report = "\n".join([
        "# Batch 1 data-quality report", "", f"- Standard observations: {len(standard):,}", f"- Derived observations: {len(panel):,}", f"- Core banks: {panel.bank_id.nunique():,}", f"- Field-mapping rows: {len(mapping):,}", f"- Duplicate standard bank/date/raw-code keys: {int(standard.duplicated(['bank_id', 'report_date', 'raw_code']).sum())}", f"- Negative NCO observations retained: {int((panel.segment_nco < 0).sum())}", f"- FDIC merger quarters flagged: {int(panel.merger_quarter_flag.sum())}", f"- Asset-jump quarters flagged: {int(panel.asset_jump_flag.sum())}", f"- Manual formula-audit failures: {int((audit.pass_fail == 'fail').sum())}", "", "## Definitions", "", "- Mortgage is closed-end 1-4 family residential lending only: RC-C RCON/RCFD5367 + 5368 and RI-B RIADC234 + C235 - C217 - C218. Revolving/open-end RCON/RCFD1797 is excluded.", "- Segment NPL is unavailable in a stable mapping. `bank_total_npl`, `bank_total_npl_ratio`, and their lags are bank-level fallback controls; `segment_npl_rate` is deliberately missing rather than total NPL divided by segment exposure.", "- `tier1_capital` and `tier1_ratio` use Schedule RC-R fields; `equity_capital` and `equity_to_assets_ratio` are separately named book-equity measures.", "- `allowance_coverage` equals allowance / bank total noncurrent loans (also named `allowance_to_total_npl`), not allowance / total loans.", "", "## NCO reconciliation rule", "", "- CRE, C&I, and mortgage are mapped loan segments, not the entire Call Report loan portfolio; their net NCO is therefore not required to equal reported total NCO.", f"- For bank-quarters with all four gross-flow values, mapped charge-offs and recoveries must each be no more than reported total plus {NCO_GROSS_FLOW_TOLERANCE_THOUSANDS:,.0f} thousand dollars.", "- A downward YTD revision explains only the corresponding gross-flow excess when the reported total for that same flow is revised downward. Unrelated or mapped-component revisions remain REVIEW_REQUIRED.", "- A directly verified source-filing inconsistency may be explained only when it is listed in `metadata/nco_reconciliation_exceptions.csv`; it remains visible in the reconciliation output.", *[f"- {status}: {count:,}" for status, count in sorted(nco_statuses.items())], f"- Open review items: {review_count:,}; see `metadata/nco_reconciliation_review.md`.", "", "## Mapped raw-field presence", "", *[f"- {date}: {count} mapped raw codes" for date, count in mapping_validation.items()], "", "## Limitations", "", "- The historical Call Report taxonomy has genuine reporting-detail changes. Missing segment detail remains missing; it is never filled with zero.", "- FDIC history events are branch-granular and collapsed to bank-quarter merger flags; no virtual-bank reconstruction is claimed.", "- `metadata/manual_source_audit.csv` records the independent raw-archive source-document sample; the deterministic audit is retained as a separate formula control.", ""
    ])
    (qa_dir / "data_quality_report.md").write_text(report, encoding="utf-8")
    return recon, audit
