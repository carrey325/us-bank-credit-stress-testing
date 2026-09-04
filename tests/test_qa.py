from pathlib import Path

import pandas as pd

from bankstress.qa.report import write_qa


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
