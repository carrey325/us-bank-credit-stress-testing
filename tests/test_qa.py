from pathlib import Path

import pandas as pd

from bankstress.qa.report import write_qa


def _standard_with_reclass(revised_metric: str | None = None) -> pd.DataFrame:
    dates = pd.to_datetime(["2025-03-31", "2025-06-30"])
    rows = []
    for metric, segment, raw_code in [
        ("total_charge_off", "All", "TOTAL_CO"), ("total_recovery", "All", "TOTAL_REC"),
        ("charge_off", "CRE", "MAPPED_CO"), ("recovery", "CRE", "MAPPED_REC"),
    ]:
        values = [100, 90] if metric == revised_metric else [100, 200]
        rows.extend({"bank_id": "1", "report_date": date, "standard_metric": metric, "segment": segment, "raw_code": raw_code, "numeric_value": value, "stock_flow": "flow"} for date, value in zip(dates, values, strict=True))
    return pd.DataFrame(rows)


def _panel_with_gross_flows(mapped_charge_off: float, mapped_recovery: float, total_charge_off: float = 100, total_recovery: float = 20) -> pd.DataFrame:
    return pd.DataFrame([{
        "bank_id": "1", "report_date": pd.Timestamp("2025-06-30"), "segment": "CRE", "exposure": 1_000,
        "charge_off": mapped_charge_off, "recovery": mapped_recovery, "segment_nco": mapped_charge_off - mapped_recovery,
        "total_loans": 5_000, "total_charge_off": total_charge_off, "total_recovery": total_recovery,
        "tier1_capital": 500, "risk_weighted_assets": 5_000, "tier1_ratio": 0.1, "computed_tier1_ratio": 0.1,
        "equity_capital": 600, "equity_to_assets_ratio": 0.1,
        "total_assets": 6_000, "merger_quarter_flag": 0, "asset_jump_flag": 0,
    }])


def test_nco_reconciliation_passes_when_mapped_gross_flows_are_a_subset(tmp_path: Path):
    recon, _ = write_qa(_standard_with_reclass(), _panel_with_gross_flows(90, 10), pd.DataFrame(), tmp_path)
    assert recon.loc[0, "nco_reconciliation_status"] == "PASS_SUBSET_GROSS_FLOWS"


def test_nco_reconciliation_requires_review_for_genuine_gross_flow_excess(tmp_path: Path):
    recon, _ = write_qa(_standard_with_reclass(), _panel_with_gross_flows(151, 10), pd.DataFrame(), tmp_path)
    assert recon.loc[0, "nco_reconciliation_status"] == "REVIEW_REQUIRED"


def test_unrelated_ytd_reclass_does_not_explain_another_gross_flow_mismatch(tmp_path: Path):
    recon, _ = write_qa(_standard_with_reclass("recovery"), _panel_with_gross_flows(151, 10), pd.DataFrame(), tmp_path)
    assert recon.loc[0, "mapped_recovery_reclass_flag"] == 1
    assert recon.loc[0, "charge_off_ytd_reclass_causally_explains"] == False
    assert recon.loc[0, "nco_reconciliation_status"] == "REVIEW_REQUIRED"


def test_total_flow_ytd_reclass_explains_only_its_matching_gross_flow_excess(tmp_path: Path):
    recon, _ = write_qa(_standard_with_reclass("total_charge_off"), _panel_with_gross_flows(151, 10), pd.DataFrame(), tmp_path)
    assert recon.loc[0, "total_charge_off_reclass_flag"] == 1
    assert recon.loc[0, "charge_off_ytd_reclass_causally_explains"] == True
    assert recon.loc[0, "nco_reconciliation_status"] == "EXPLAINED_YTD_RECLASS_GROSS_FLOW"


def test_nco_reconciliation_records_only_explicit_source_exception(tmp_path: Path):
    dates = pd.to_datetime(["2025-03-31", "2025-06-30"])
    standard = pd.DataFrame([
        {"bank_id": "1", "report_date": dates[0], "standard_metric": "total_charge_off", "segment": "All", "raw_code": "RIAD4635", "numeric_value": 100, "stock_flow": "flow"},
        {"bank_id": "1", "report_date": dates[1], "standard_metric": "total_charge_off", "segment": "All", "raw_code": "RIAD4635", "numeric_value": 200, "stock_flow": "flow"},
    ])
    panel = pd.DataFrame([{
        "bank_id": "1", "report_date": dates[1], "segment": "CRE", "exposure": 1_000,
        "charge_off": 200, "recovery": 80, "segment_nco": 120, "total_loans": 5_000,
        "total_charge_off": 100, "total_recovery": 0, "tier1_capital": 500, "total_assets": 6_000,
        "merger_quarter_flag": 0, "asset_jump_flag": 0,
    }])
    exceptions = pd.DataFrame([{"bank_id": "1", "report_date": "2025-06-30", "exception_type": "source_filing_internal_recovery_difference"}])
    recon, _ = write_qa(standard, panel, pd.DataFrame(), tmp_path, exceptions)
    assert recon.loc[0, "nco_reconciliation_status"] == "EXPLAINED_SOURCE_FILING_INCONSISTENCY"
    assert recon.loc[0, "recovery_subset_difference"] == 80


def test_capital_reconciliation_compares_tier1_over_rwa_to_reported_ratio(tmp_path: Path):
    panel = _panel_with_gross_flows(90, 10)
    panel.loc[0, "computed_tier1_ratio"] = panel.loc[0, "tier1_capital"] / panel.loc[0, "risk_weighted_assets"]
    recon, _ = write_qa(_standard_with_reclass(), panel, pd.DataFrame(), tmp_path)
    assert recon.loc[0, "capital_reconciliation_status"] == "PASS_WITHIN_TOLERANCE"
    assert recon.loc[0, "capital_ratio_difference_basis_points"] == 0


def test_capital_reconciliation_flags_ratio_outside_one_basis_point(tmp_path: Path):
    panel = _panel_with_gross_flows(90, 10)
    panel.loc[0, "tier1_ratio"] = 0.1011
    recon, _ = write_qa(_standard_with_reclass(), panel, pd.DataFrame(), tmp_path)
    assert recon.loc[0, "capital_reconciliation_status"] == "FAIL_OUTSIDE_TOLERANCE"
