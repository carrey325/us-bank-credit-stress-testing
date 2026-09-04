from pathlib import Path

import pandas as pd
import pytest

from bankstress.transform.panel import _aggregate_complete_flows, _coalesce_reporting_variants, build_credit_panel


def test_ci_aggregate_is_not_added_to_geographic_breakout():
    data = pd.DataFrame([
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCON1766", "numeric_value": 100, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1763", "numeric_value": 95, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "exposure", "segment": "CI", "raw_code": "RCFD1764", "numeric_value": 5, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "ci_exposure"},
    ])
    result = _coalesce_reporting_variants(data)
    assert result.numeric_value.tolist() == [100]


def test_rc_r_a_w_reporting_variants_are_coalesced_not_summed():
    data = pd.DataFrame([
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "tier1_risk_based_ratio", "segment": "All", "raw_code": "RCFA7206", "numeric_value": 0.12, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "regulatory_capital"},
        {"bank_id": "1", "report_date": "2020-03-31", "standard_metric": "tier1_risk_based_ratio", "segment": "All", "raw_code": "RCFW7206", "numeric_value": 0.12, "stock_flow": "stock", "ytd_flag": 0, "formula_group": "regulatory_capital"},
    ])
    result = _coalesce_reporting_variants(data)
    assert len(result) == 1
    assert result.loc[0, "numeric_value"] == 0.12


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
            "risk_weighted_assets": [200, 220, 250],
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
    assert second_quarter["computed_tier1_ratio"].tolist() == [0.10, 0.10, 0.10]
    assert second_quarter["equity_to_assets_ratio"].tolist() == [0.5, 0.5, 0.5]
    assert second_quarter["allowance_coverage"].tolist() == pytest.approx([11 / 6, 11 / 6, 11 / 6])
    assert panel.loc[panel["report_date"].eq(dates[0]), "asset_jump_flag"].tolist() == [0, 0, 0]
    assert panel.loc[panel["report_date"].eq(dates[2]), "asset_jump_flag"].tolist() == [1, 1, 1]


def test_mortgage_mapping_is_closed_end_and_includes_both_lien_nco_components():
    mapping = pd.read_csv(Path(__file__).parents[1] / "metadata" / "field_mapping.csv")
    mortgage = mapping.loc[mapping["segment"].eq("Mortgage")]
    assert not mortgage["raw_code"].isin(["RCON1797", "RCFD1797"]).any()
    assert {"RCON5367", "RCON5368", "RCFD5367", "RCFD5368", "RIADC234", "RIADC217", "RIADC235", "RIADC218"}.issubset(set(mortgage["raw_code"]))
    consolidated = mortgage.loc[mortgage["raw_code"].isin(["RCFD5367", "RCFD5368"])]
    assert consolidated["start_date"].eq("2013-06-30").all()
    assert consolidated["form"].eq("031").all()


def test_cre_mapping_uses_complete_predecessor_and_successor_taxonomies():
    mapping = pd.read_csv(Path(__file__).parents[1] / "metadata" / "field_mapping.csv")
    cre_flows = mapping.loc[mapping["segment"].eq("CRE") & mapping["standard_metric"].isin(["charge_off", "recovery"])]
    legacy = cre_flows.loc[cre_flows["raw_code"].isin(["RIAD3582", "RIAD3583", "RIAD3590", "RIAD3591"])]
    successor = cre_flows.loc[cre_flows["raw_code"].str.match(r"RIADC89[1-8]")]
    assert legacy["end_date"].eq("2007-12-31").all()
    assert set(successor["raw_code"]) == {f"RIADC{code}" for code in range(891, 899)}
    assert successor["start_date"].eq("2008-03-31").all()


def _cre_flow_rows(date: str, charge_value: float, recovery_value: float, omit: set[str] | None = None) -> list[dict[str, object]]:
    omit = omit or set()
    components = {
        "charge_off": ["RIADC891", "RIADC893", "RIAD3588", "RIADC895", "RIADC897"],
        "recovery": ["RIADC892", "RIADC894", "RIAD3589", "RIADC896", "RIADC898"],
    }
    values = {"charge_off": charge_value, "recovery": recovery_value}
    return [
        {"bank_id": "1", "report_date": date, "standard_metric": metric, "segment": "CRE", "raw_code": code,
         "numeric_value": values[metric], "formula_group": "cre_nco"}
        for metric, codes in components.items() for code in codes if code not in omit
    ]


def _legacy_cre_flow_rows(date: str, charge_value: float, recovery_value: float) -> list[dict[str, object]]:
    components = {
        "charge_off": ["RIAD3582", "RIAD3588", "RIAD3590"],
        "recovery": ["RIAD3583", "RIAD3589", "RIAD3591"],
    }
    values = {"charge_off": charge_value, "recovery": recovery_value}
    return [
        {"bank_id": "1", "report_date": date, "standard_metric": metric, "segment": "CRE", "raw_code": code,
         "numeric_value": values[metric], "formula_group": "cre_nco"}
        for metric, codes in components.items() for code in codes
    ]


def test_cre_year_boundary_transitions_from_reported_aggregates_to_complete_split_components():
    flows = pd.DataFrame(
        _legacy_cre_flow_rows("2007-09-30", 10, 2)
        + _legacy_cre_flow_rows("2007-12-31", 15, 3)
        + _cre_flow_rows("2008-03-31", 2, 1)
    )
    result = _aggregate_complete_flows(flows)
    q4 = result.loc[result["report_date"].eq("2007-12-31")].set_index("standard_metric")
    q1 = result.loc[result["report_date"].eq("2008-03-31")].set_index("standard_metric")
    assert q4.loc["charge_off", "value"] == 15
    assert q4.loc["recovery", "value"] == 3
    assert q1.loc["charge_off", "value"] == 10
    assert q1.loc["recovery", "value"] == 5
    assert pd.concat([q4["component_complete_flag"], q1["component_complete_flag"]]).eq(1).all()


def test_cre_successor_flow_sums_every_construction_and_nonfarm_component():
    flows = pd.DataFrame(_cre_flow_rows("2008-03-31", 2, 1) + _cre_flow_rows("2008-06-30", 5, 2))
    result = _aggregate_complete_flows(flows)
    q1 = result.loc[result["report_date"].eq("2008-03-31")].set_index("standard_metric")
    q2 = result.loc[result["report_date"].eq("2008-06-30")].set_index("standard_metric")
    assert q1.loc["charge_off", "value"] == 10
    assert q1.loc["recovery", "value"] == 5
    assert q2.loc["charge_off", "value"] == 15
    assert q2.loc["recovery", "value"] == 5
    assert result["component_complete_flag"].eq(1).all()


def test_cre_flow_is_missing_when_a_required_component_cannot_be_quarterized():
    flows = pd.DataFrame(
        _cre_flow_rows("2008-03-31", 2, 1, omit={"RIADC891"})
        + _cre_flow_rows("2008-06-30", 5, 2)
    )
    result = _aggregate_complete_flows(flows)
    charge_off = result.loc[
        result["report_date"].eq("2008-06-30") & result["standard_metric"].eq("charge_off")
    ].iloc[0]
    assert pd.isna(charge_off["value"])
    assert charge_off["component_complete_flag"] == 0
    assert charge_off["missing_flow_components"] == "RIADC891"


def test_capital_mapping_has_legacy_and_post_2014_ratio_and_rwa_variants():
    mapping = pd.read_csv(Path(__file__).parents[1] / "metadata" / "field_mapping.csv")
    codes = set(mapping["raw_code"])
    assert {"RCFA7206", "RCFW7206", "RCOA7206", "RCOW7206"}.issubset(codes)
    assert {"RCONA223", "RCFDA223", "RCFAA223", "RCFWA223", "RCOAA223", "RCOWA223"}.issubset(codes)
    legacy = mapping.loc[mapping["raw_code"].isin(["RCON7206", "RCFD7206", "RCONA223", "RCFDA223"])]
    assert legacy["end_date"].eq("2014-12-31").all()
