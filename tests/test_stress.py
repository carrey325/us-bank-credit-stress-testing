from pathlib import Path
import copy

import numpy as np
import pandas as pd
import pytest
import bankstress.stress as stress_module

from bankstress.stress import (
    R4_FORMAL_PAIRS,
    _annualized_to_qoq_percent,
    _freeze_controls,
    _normalise_fed_frame,
    construct_stress_macro_predictors,
    make_sensitivity_scenarios,
    recursive_stress_paths,
    validate_formal_r4_inputs,
    summarize_stress,
    StressFit,
)
from bankstress.macro import _quarterly


def _fed(name: str, gdp: float, cre: float, house: float) -> pd.DataFrame:
    return pd.DataFrame({"Date": ["2026 Q1", "2026 Q2"], "Real GDP growth": [gdp, gdp], "Unemployment rate": [5.0, 6.0], "Commercial Real Estate Price Index (Level)": [cre, cre - 1], "House Price Index (Level)": [house, house - 1], "BBB corporate yield": [6.0, 6.0], "3-month Treasury rate": [3.0, 3.0], "10-year Treasury yield": [4.0, 4.0], "Mortgage rate": [6.0, 6.0]})


def test_fed_normalisation_anchors_q1_price_growth_and_converts_gdp_units():
    history = pd.DataFrame({"quarter": pd.date_range("2025-03-31", periods=4, freq="QE"), "cre_price": [100.0] * 4, "house_price": [200.0, 200.0, 200.0, 200.0]})
    normal = _normalise_fed_frame(_fed("baseline", 4.0, 110.0, 210.0), "baseline", history)
    assert np.isclose(normal.iloc[0].cre_price_growth, 10.0)
    assert np.isclose(normal.iloc[0].house_price_growth, 5.0)
    assert np.isclose(normal.iloc[0].gdp_growth, _annualized_to_qoq_percent(pd.Series([4.0])).iloc[0])
    assert normal.iloc[0].bbb_spread == 2.0


def test_historical_and_fed_cre_growth_use_matching_yoy_percent_units():
    # COMREPUSQ159N reports this historical value directly as YoY percent growth.
    historical = pd.DataFrame({"observation_date": pd.to_datetime(["2025-03-31"]), "value": [5.0]})
    historical_growth = _quarterly(historical, "quarter_end", "reported_yoy_pct_change")
    levels = pd.DataFrame({"quarter": pd.date_range("2025-03-31", periods=4, freq="QE"), "cre_price": [100.0, 100.0, 100.0, 100.0], "house_price": [200.0, 200.0, 200.0, 200.0]})
    fed = _normalise_fed_frame(_fed("baseline", 4.0, 105.0, 210.0), "baseline", levels)
    assert historical_growth.iloc[0].value == 5.0
    assert fed.iloc[0].cre_price_growth == pytest.approx(5.0)


def test_lambda_and_partial_shocks_are_labelled_researcher_sensitivities():
    historic = pd.DataFrame({
        "quarter": pd.date_range("2025-03-31", periods=4, freq="QE"),
        "cre_price": [100.0] * 4,
        "house_price": [200.0] * 4,
        "short_rate": [4.0] * 4,
        "long_rate": [5.0] * 4,
        "mortgage_rate": [6.5] * 4,
    })
    baseline = _normalise_fed_frame(_fed("baseline", 2.0, 101.0, 201.0), "baseline", historic).assign(horizon=[1, 2], scenario_type="Fed official")
    severe = _normalise_fed_frame(_fed("severe", -4.0, 91.0, 191.0), "severely_adverse", historic).assign(horizon=[1, 2], scenario_type="Fed official")
    result = make_sensitivity_scenarios(pd.concat([baseline, severe]), historic, [0.5, 1.0, 1.25])
    assert set(result.scenario) >= {"researcher_lambda_0.5", "researcher_lambda_1", "researcher_lambda_1.25", "researcher_cre_only", "researcher_unemployment_only", "researcher_high_for_longer_rates"}
    assert result.scenario_type.str.startswith("Researcher").all()
    assert result.cre_price_growth.notna().all()


def test_loss_summary_uses_rate_times_static_exposure_and_allowance_floor():
    paths = pd.DataFrame({"bank_id": ["1", "1"], "bank_name": ["A", "A"], "scenario": ["severely_adverse"] * 2, "scenario_type": ["Fed official"] * 2, "model": ["dynamic_fe"] * 2, "segment": ["CRE", "CI"], "predicted_loss": [20.0, 30.0], "starting_tier1": [100.0, 100.0], "starting_allowance": [40.0, 40.0], "starting_loans": [500.0, 500.0]})
    summary, _ = summarize_stress(paths)
    assert summary.iloc[0].cumulative_loss == 50.0
    assert summary.iloc[0].capital_depletion == 0.5
    assert summary.iloc[0].allowance_adjusted_loss == 10.0


def test_recursive_paths_keep_raw_nco_state_and_floor_only_dollar_losses():
    jump = pd.DataFrame({"bank_id": ["1"], "bank_name": ["A"], "segment": ["CRE"], "nco_rate": [0.01], "exposure": [1000.0], "tier1_capital": [100.0], "allowance": [10.0], "total_loans": [1000.0], "npl_rate": [0.02], "allowance_coverage": [1.0], "loan_growth": [0.0], "tier1_ratio": [0.1]})
    scenarios = pd.DataFrame({"scenario": ["baseline", "baseline"], "scenario_type": ["Fed official"] * 2, "quarter": pd.to_datetime(["2026-03-31", "2026-06-30"]), "horizon": [1, 2], "lagged_gdp_growth": [9.0, 1.0], "lagged_gdp_growth_source_quarter": pd.to_datetime(["2025-12-31", "2026-03-31"])})
    # A tiny FE-compatible fit whose entity means make the predicted rate -1%.
    fit = {"CRE": {"predictors": ["lagged_nco_rate", "lagged_gdp_growth"], "beta": np.array([0.0, 0.0]), "entity_means": pd.DataFrame({"nco_rate": [-0.01], "lagged_nco_rate": [0.0], "lagged_gdp_growth": [0.0]}, index=["1::CRE"])} }
    model = StressFit("dynamic_fe", "fe", fit, {"CRE": ["lagged_nco_rate", "lagged_gdp_growth"]})
    paths = recursive_stress_paths(jump, scenarios, [model])
    assert paths.predicted_nco_rate.eq(-0.01).all()
    assert paths.predicted_loss.eq(0).all()
    assert paths.lagged_gdp_growth_source_quarter.tolist() == [pd.Timestamp("2025-12-31"), pd.Timestamp("2026-03-31")]
    positive_fit = {"CRE": {**fit["CRE"], "entity_means": fit["CRE"]["entity_means"].assign(nco_rate=0.01)}}
    positive = recursive_stress_paths(jump, scenarios.iloc[:1], [StressFit("dynamic_fe", "fe", positive_fit, model.predictors)])
    assert np.isclose(positive.iloc[0].predicted_loss, 1000.0 * 0.01 / 4)


def test_jump_off_controls_use_actual_2025q4_state_not_stale_lagged_columns():
    jump = pd.DataFrame({"bank_id": ["1"], "npl_rate": [0.02], "allowance_coverage": [1.5], "loan_growth": [0.04], "tier1_ratio": [0.11], "lagged_noncurrent_ratio": [0.01], "lagged_allowance_coverage": [0.9], "lagged_loan_growth": [-0.02], "lagged_tier1_ratio": [0.10]})
    state = _freeze_controls(jump, pd.DataFrame({"bank_id": ["1"]}), ["lagged_noncurrent_ratio", "lagged_allowance_coverage", "lagged_loan_growth", "lagged_tier1_ratio"])
    assert state.iloc[0][["lagged_noncurrent_ratio", "lagged_allowance_coverage", "lagged_loan_growth", "lagged_tier1_ratio"]].tolist() == [0.02, 1.5, 0.04, 0.11]


def test_future_macro_predictors_preserve_batch2_availability_and_lag_semantics():
    actual = pd.DataFrame({
        "quarter": pd.to_datetime(["2025-09-30", "2025-12-31"]),
        "gdp_growth": [30.0, 40.0], "unemployment": [30.0, 40.0], "cre_price_growth": [30.0, 40.0],
        "house_price_growth": [30.0, 40.0], "bbb_spread": [30.0, 40.0], "short_rate": [30.0, 40.0], "mortgage_rate": [30.0, 40.0],
    })
    scenario = pd.DataFrame({
        "scenario": ["baseline"] * 3, "scenario_type": ["Fed official"] * 3,
        "quarter": pd.to_datetime(["2026-03-31", "2026-06-30", "2026-09-30"]), "horizon": [1, 2, 3],
        "gdp_growth": [100.0, 200.0, 300.0], "unemployment": [100.0, 200.0, 300.0], "cre_price_growth": [100.0, 200.0, 300.0],
        "house_price_growth": [100.0, 200.0, 300.0], "bbb_spread": [100.0, 200.0, 300.0], "short_rate": [100.0, 200.0, 300.0], "mortgage_rate": [100.0, 200.0, 300.0],
    })
    prepared = construct_stress_macro_predictors(scenario, actual, Path(__file__).resolve().parents[1])
    vintage = ["lagged_gdp_growth", "lagged_unemployment_rate"]
    fallback = ["lagged_cre_price_growth", "lagged_house_price_growth", "lagged_bbb_spread", "lagged_short_rate", "lagged_mortgage_rate"]
    assert prepared.loc[0, vintage].tolist() == [40.0, 40.0]
    assert prepared.loc[0, fallback].tolist() == [30.0] * len(fallback)
    assert prepared.loc[1, vintage].tolist() == [100.0, 100.0]
    assert prepared.loc[1, fallback].tolist() == [40.0] * len(fallback)
    assert prepared.loc[2, vintage].tolist() == [200.0, 200.0]
    assert prepared.loc[2, fallback].tolist() == [100.0] * len(fallback)
    assert prepared.loc[0, "lagged_gdp_growth_source_quarter"] == pd.Timestamp("2025-12-31")
    assert prepared.loc[0, "lagged_cre_price_growth_source_quarter"] == pd.Timestamp("2025-09-30")


def test_current_formal_r4_gate_accepts_only_registry_authorized_pairs():
    root = Path(__file__).resolve().parents[1]
    gate = validate_formal_r4_inputs(root)
    registry = {(item["model_id"], item["segment"]): item for item in gate["registry"]}
    assert set(R4_FORMAL_PAIRS) == {("ar_mean", "CI"), ("ar_mean", "CRE"), ("dynamic_fe", "CI")}
    assert all(registry[pair]["conditional_mean_stress_use"] == "ALLOWED" for pair in R4_FORMAL_PAIRS)
    assert registry[("dynamic_fe", "CRE")]["conditional_mean_stress_use"] == "DIAGNOSTIC_ONLY"


def test_formal_r4_gate_rejects_legacy_residual_input():
    root = Path(__file__).resolve().parents[1]
    residual = root / "outputs/model_risk/rolling_residual_intervals.parquet"
    with pytest.raises(ValueError, match="does not authorize residual/extra formal inputs"):
        validate_formal_r4_inputs(root, additional_formal_artifacts=[residual])


@pytest.mark.parametrize("stale_kind", ["r1_mapping", "r2_model", "r3_registry"])
def test_formal_r4_gate_rejects_stale_upstream_lineage(monkeypatch, stale_kind):
    root = Path(__file__).resolve().parents[1]
    real_metadata = stress_module.validate_artifact_metadata
    real_json = stress_module._read_json

    def fake_metadata(path, **kwargs):
        payload = copy.deepcopy(real_metadata(path, **kwargs))
        if stale_kind == "r1_mapping" and path.name == "credit_panel.parquet":
            payload["field_mapping_hash"] = "stale-r1-mapping"
        if stale_kind == "r2_model" and path.name == "coefficients.csv":
            payload["input_artifact_hashes"]["data/derived/model_panel.parquet"] = "stale-r2-model-panel"
        return payload

    def fake_json(path):
        payload = copy.deepcopy(real_json(path))
        if stale_kind == "r3_registry" and path.name == "model_use_registry.json":
            payload[0]["input_run_id"] = "stale-r2-run"
        return payload

    monkeypatch.setattr(stress_module, "validate_artifact_metadata", fake_metadata)
    monkeypatch.setattr(stress_module, "_read_json", fake_json)
    with pytest.raises(ValueError, match="Formal R4 lineage gate failed"):
        validate_formal_r4_inputs(root)


def test_generated_r4_paths_have_exact_scope_horizon_formula_and_lineage():
    root = Path(__file__).resolve().parents[1]
    paths = pd.read_parquet(root / "outputs/stress/stress_paths.parquet")
    assert set(zip(paths.model, paths.segment)) == set(R4_FORMAL_PAIRS)
    assert set(paths.horizon) == set(range(1, 10))
    assert set(paths.loc[paths.scenario.isin(["baseline", "severely_adverse"]), "scenario"]) == {"baseline", "severely_adverse"}
    expected = paths.loss_rate_for_aggregation_decimal_annualized / 4 * paths.exposure_thousands
    assert np.allclose(paths.quarter_loss_thousands, expected)
    required_lineage = {
        "lagged_nco_rate_source_quarter", "lagged_nco_rate_source_type",
        "exposure_source_quarter", "exposure_assumption",
    }
    assert required_lineage.issubset(paths.columns)
    assert paths[list(required_lineage)].notna().all().all()
