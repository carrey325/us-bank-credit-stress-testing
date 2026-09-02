import pandas as pd

from bankstress.transform.panel import _coalesce_reporting_variants


def test_ci_aggregate_is_not_added_to_geographic_breakout():
    data = pd.DataFrame([
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCON1766", "numeric_value": 100, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1763", "numeric_value": 95, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1764", "numeric_value": 5, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
    ])
    result = _coalesce_reporting_variants(data)
    assert result.numeric_value.tolist() == [100]
