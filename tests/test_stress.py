from pathlib import Path

import numpy as np
import pandas as pd

from bankstress.stress import (
    _annualized_to_qoq_percent,
    _freeze_controls,
    _normalise_fed_frame,
    construct_stress_macro_predictors,
    make_sensitivity_scenarios,
    recursive_stress_paths,
    summarize_stress,
    StressFit,
)


def _fed(name: str, gdp: float, cre: float, house: float) -> pd.DataFrame:
    return pd.DataFrame({"Date": ["2026 Q1", "2026 Q2"], "Real GDP growth": [gdp, gdp], "Unemployment rate": [5.0, 6.0], "Commercial Real Estate Price Index (Level)": [cre, cre - 1], "House Price Index (Level)": [house, house - 1], "BBB corporate yield": [6.0, 6.0], "3-month Treasury rate": [3.0, 3.0], "10-year Treasury yield": [4.0, 4.0], "Mortgage rate": [6.0, 6.0]})


def test_fed_normalisation_anchors_q1_price_growth_and_converts_gdp_units():
    normal = _normalise_fed_frame(_fed("baseline", 4.0, 110.0, 210.0), "baseline", pd.Series({"cre_price": 100.0, "house_price": 200.0}))
    assert np.isclose(normal.iloc[0].cre_price_growth, 10.0)
    assert np.isclose(normal.iloc[0].house_price_growth, 5.0)
    assert np.isclose(normal.iloc[0].gdp_growth, _annualized_to_qoq_percent(pd.Series([4.0])).iloc[0])
    assert normal.iloc[0].bbb_spread == 2.0


def test_lambda_and_partial_shocks_are_labelled_researcher_sensitivities():
    historic = pd.Series({"cre_price": 100.0, "house_price": 200.0, "short_rate": 4.0, "long_rate": 5.0, "mortgage_rate": 6.5})
    baseline = _normalise_fed_frame(_fed("baseline", 2.0, 101.0, 201.0), "baseline", historic).assign(horizon=[1, 2], scenario_type="Fed official")
    severe = _normalise_fed_frame(_fed("severe", -4.0, 91.0, 191.0), "severely_adverse", historic).assign(horizon=[1, 2], scenario_type="Fed official")
    result = make_sensitivity_scenarios(pd.concat([baseline, severe]), historic, [0.5, 1.0, 1.25])
    assert set(result.scenario) >= {"researcher_lambda_0.5", "researcher_lambda_1", "researcher_lambda_1.25", "researcher_cre_only", "researcher_unemployment_only", "researcher_high_for_longer_rates"}
    assert result.scenario_type.str.startswith("Researcher").all()


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
