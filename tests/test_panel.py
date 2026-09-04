from pathlib import Path

import pandas as pd
import pytest

from bankstress.transform.panel import _coalesce_reporting_variants, build_credit_panel


def test_ci_aggregate_is_not_added_to_geographic_breakout():
    data = pd.DataFrame([
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCON1766", "numeric_value": 100, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1763", "numeric_value": 95, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1764", "numeric_value": 5, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
    ])
    result = _coalesce_reporting_variants(data)
    assert result.numeric_value.tolist() == [100]


def test_bank_quarter_features_are_computed_before_segment_broadcast():
    dates = pd.to_datetime(["2020-03-31", "2020-06-30", "2020-09-30"])
    rows = []
    for index, date in enumerate(dates):
        for segment, exposure in {"CRE": [40, 44, 48][index], "CI": [30, 33, 36][index], "Mortgage": [20, 22, 24][index]}.items():
            rows.extend([
                {"bank_id": "1", "report_date": date, "standard_metric": "exposure", "segment": segment, "raw_code": f"EXP_{segment}", "numeric_value": exposure, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "test"},
                {"bank_id": "1", "report_date": date, "standard_metric": "charge_off", "segment": segment, "raw_code": f"CO_{segment}", "numeric_value": index + 1, "stock_flow": "flow", "ytd_flag": 1, "formula_group": "test"},
                {"bank_id": "1", "report_date": date, "standard_metric": "recovery", "segment": segment, "raw_code": f"REC_{segment}", "numeric_value": 0, "stock_flow": "flow", "ytd_flag": 1, "formula_group": "test"},
            ])
        for metric, values in {
            "total_loans": [100, 110, 120], "total_assets": [100, 110, 200], "total_npl": [5, 6, 9],
            "allowance": [10, 11, 12], "equity_capital": [50, 55, 60], "tier1_capital": [20, 22, 25],
            "tier1_risk_based_ratio": [0.10, 0.10, 0.11],
        }.items():
            rows.append({"bank_id": "1", "report_date": date, "standard_metric": metric, "segment": "All", "raw_code": metric, "numeric_value": values[index], "stock_flow": "stock", "ytd_flag": 0, "formula_group": "test"})
    panel = build_credit_panel(pd.DataFrame(rows), pd.DataFrame([{"bank_id": "1", "cert": "1", "bank_name": "Test"}]), {"sample": {"small_exposure_thousands": 1}})
    second_quarter = panel.loc[panel["report_date"].eq(dates[1])]
    assert second_quarter["loan_growth"].tolist() == pytest.approx([0.1, 0.1, 0.1])
    assert second_quarter["lagged_npl"].tolist() == [5, 5, 5]
    assert second_quarter["lagged_bank_total_npl_ratio"].tolist() == [0.05, 0.05, 0.05]
    assert second_quarter["segment_npl_rate"].isna().all()
    assert second_quarter["tier1_ratio"].tolist() == [0.10, 0.10, 0.10]
    assert second_quarter["equity_to_assets_ratio"].tolist() == [0.5, 0.5, 0.5]
    assert second_quarter["allowance_coverage"].tolist() == pytest.approx([11 / 6, 11 / 6, 11 / 6])
    assert panel.loc[panel["report_date"].eq(dates[2]), "asset_jump_flag"].tolist() == [1, 1, 1]


def test_mortgage_mapping_is_closed_end_and_includes_both_lien_nco_components():
    mapping = pd.read_csv(Path(__file__).parents[1] / "metadata" / "field_mapping.csv")
    mortgage = mapping.loc[mapping["segment"].eq("Mortgage")]
    assert not mortgage["raw_code"].isin(["RCON1797", "RCFD1797"]).any()
    assert {"RCON5367", "RCON5368", "RCFD5367", "RCFD5368", "RIADC234", "RIADC217", "RIADC235", "RIADC218"}.issubset(set(mortgage["raw_code"]))
