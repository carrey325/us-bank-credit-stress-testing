import json
from pathlib import Path

import pandas as pd

from bankstress.artifacts import R1_DEFINITION_VERSION, validate_artifact_metadata
from bankstress.transform.panel import _aggregate_complete_stocks, build_credit_panel


ROOT = Path(__file__).parents[1]


def _stock_rows(date: str, form: str, codes: dict[str, float | None]) -> pd.DataFrame:
    return pd.DataFrame([
        {"bank_id": "1", "report_date": pd.Timestamp(date), "form": form, "standard_metric": "exposure",
         "segment": "CRE", "raw_code": code, "numeric_value": value, "formula_group": "cre_exposure",
         "stock_flow": "stock", "ytd_flag": 0}
        for code, value in codes.items()
    ])


def test_missing_required_cre_stock_component_suppresses_exposure():
    stocks = _stock_rows("2020-03-31", "41", {
        "RCONF158": 10, "RCONF159": 20, "RCON1460": 30, "RCONF160": 40, "RCONF161": None,
    })
    result = _aggregate_complete_stocks(stocks).iloc[0]
    assert pd.isna(result["value"])
    assert result["exposure_status"] == "MISSING_REQUIRED"
    assert result["missing_stock_components"] == "RCONF161"


def test_2746_memo_item_cannot_complete_secured_cre_exposure():
    result = _aggregate_complete_stocks(_stock_rows("2020-03-31", "41", {"RCON2746": 999})).iloc[0]
    assert pd.isna(result["value"])
    assert result["exposure_complete"] == 0
    mapping = pd.read_csv(ROOT / "metadata" / "field_mapping.csv")
    assert not mapping.loc[mapping["segment"].eq("CRE") & mapping["standard_metric"].eq("exposure"), "raw_code"].isin(["RCON2746", "RCFD2746"]).any()


def test_legacy_total_and_successor_subitems_are_not_double_counted():
    result = _aggregate_complete_stocks(_stock_rows("2007-12-31", "41", {
        "RCON1415": 10, "RCON1460": 20, "RCON1480": 30,
        "RCONF158": 4, "RCONF159": 6, "RCONF160": 10, "RCONF161": 20,
    })).iloc[0]
    assert result["value"] == 60
    assert result["mapping_id"] == "CRE_041_legacy_secured_re"


def test_stock_status_distinguishes_reported_zero_blank_and_not_applicable():
    zero = _aggregate_complete_stocks(_stock_rows("2007-12-31", "41", {"RCON1415": 0, "RCON1460": 0, "RCON1480": 0})).iloc[0]
    blank = _aggregate_complete_stocks(_stock_rows("2007-12-31", "41", {"RCON1415": 0, "RCON1460": None, "RCON1480": 0})).iloc[0]
    unavailable = _aggregate_complete_stocks(_stock_rows("2010-03-31", "31", {"RCON1415": 10})).iloc[0]
    assert zero["exposure_status"] == "REPORTED_ZERO" and zero["value"] == 0
    assert blank["exposure_status"] == "MISSING_REQUIRED" and pd.isna(blank["value"])
    assert unavailable["exposure_status"] == "NOT_APPLICABLE" and pd.isna(unavailable["value"])


def _panel_rows(dates: list[str], forms: list[str] | None = None) -> pd.DataFrame:
    rows = []
    forms = forms or ["41"] * len(dates)
    for index, (date, form) in enumerate(zip(dates, forms)):
        date = pd.Timestamp(date)
        rows += [
            {"bank_id":"1", "report_date":date, "form":form, "standard_metric":"exposure", "segment":"CI", "raw_code":"RCON1766" if form == "41" else "RCFD1763", "numeric_value":100 + index * 10, "stock_flow":"stock", "ytd_flag":0, "formula_group":"ci_exposure"},
            {"bank_id":"1", "report_date":date, "form":form, "standard_metric":"charge_off", "segment":"CI", "raw_code":"RIAD4638", "numeric_value":1 if date.quarter == 1 else 3, "stock_flow":"flow", "ytd_flag":1, "formula_group":"ci_nco"},
            {"bank_id":"1", "report_date":date, "form":form, "standard_metric":"recovery", "segment":"CI", "raw_code":"RIAD4608", "numeric_value":2 if date.quarter == 1 else 2, "stock_flow":"flow", "ytd_flag":1, "formula_group":"ci_nco"},
        ]
        if form == "31":
            rows.append({"bank_id":"1", "report_date":date, "form":form, "standard_metric":"exposure", "segment":"CI", "raw_code":"RCFD1764", "numeric_value":0, "stock_flow":"stock", "ytd_flag":0, "formula_group":"ci_exposure"})
        for metric, value in {"total_loans":200, "total_assets":300, "total_npl":2, "allowance":3, "tier1_capital":30, "risk_weighted_assets":200, "tier1_risk_based_ratio":.15}.items():
            rows.append({"bank_id":"1", "report_date":date, "form":form, "standard_metric":metric, "segment":"All", "raw_code":metric, "numeric_value":value, "stock_flow":"stock", "ytd_flag":0, "formula_group":"test"})
    return pd.DataFrame(rows)


def test_nonconsecutive_exposure_and_form_scope_change_block_average_and_rate():
    rows = _panel_rows(["2020-03-31", "2020-09-30", "2020-12-31"], ["41", "41", "31"])
    panel = build_credit_panel(rows, pd.DataFrame([{"bank_id":"1", "cert":"1", "bank_name":"Test"}]), {"sample":{"small_exposure_thousands":1}})
    assert panel["average_exposure"].isna().all()
    assert panel["annualized_nco_rate"].isna().all()


def test_negative_nco_is_retained_and_decimal_percent_units_are_distinct():
    rows = _panel_rows(["2020-03-31", "2020-06-30"])
    q2 = rows["report_date"].eq(pd.Timestamp("2020-06-30"))
    rows.loc[q2 & rows["standard_metric"].eq("charge_off"), "numeric_value"] = 1
    rows.loc[q2 & rows["standard_metric"].eq("recovery"), "numeric_value"] = 3
    panel = build_credit_panel(rows, pd.DataFrame([{"bank_id":"1", "cert":"1", "bank_name":"Test"}]), {"sample":{"small_exposure_thousands":1}})
    q2 = panel.loc[panel["report_date"].eq(pd.Timestamp("2020-06-30"))].iloc[0]
    assert q2["segment_nco"] == -1
    assert q2["annualized_nco_rate"] == 4 * (-1 / 105)
    assert q2["annualized_nco_rate_percent"] == 100 * q2["annualized_nco_rate"]
    assert q2["amount_unit"] == "USD_thousands"


def test_old_or_invalid_artifact_metadata_is_rejected(tmp_path: Path):
    artifact = tmp_path / "panel.parquet"
    artifact.write_bytes(b"old-panel")
    sidecar = artifact.with_suffix(".parquet.metadata.json")
    sidecar.write_text(json.dumps({
        "stage":"Batch1", "data_definition_version":"batch1-v3", "validation_status":"PASS", "artifact_hash":"wrong"
    }), encoding="utf-8")
    try:
        validate_artifact_metadata(artifact)
    except ValueError as error:
        assert "stage" in str(error) or R1_DEFINITION_VERSION in str(error)
    else:
        raise AssertionError("obsolete artifact metadata was accepted")
