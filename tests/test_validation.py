from pathlib import Path

import numpy as np
import pandas as pd

from bankstress.modeling import load_model_specs
from bankstress.validation import _bayesian_convergence_failure, _crisis_period_mask, fit_quantile, interval_scores, pinball_loss, predict_quantile, recursive_cre_q90_calibration_statement, write_validation_figures


def _frame() -> pd.DataFrame:
    rows = []
    for bank, effect in [("1", 0.01), ("2", 0.02), ("3", 0.03)]:
        for period in range(20):
            lag = 0.01 + period * 0.001
            rows.append({"bank_id": bank, "segment": "CRE", "report_date": pd.Timestamp("2017-03-31") + pd.offsets.QuarterEnd(period),
                         "nco_rate": effect + 0.5 * lag, "lagged_nco_rate": lag, "lagged_gdp_growth": 1 + period * 0.1})
    return pd.DataFrame(rows)


def test_quantile_uses_bank_effects_and_predicts_known_banks():
    data = _frame()
    spec = {"max_iter": 5000, "p_tol": 1e-7}
    fit = fit_quantile(data.iloc[:45], ["lagged_nco_rate", "lagged_gdp_growth"], 0.9, spec)
    prediction = predict_quantile(fit, data.iloc[45:])
    assert len(prediction) == 15
    assert prediction["prediction"].notna().all()


def test_tail_metrics_are_labelled_and_pinball_is_zero_for_exact_forecast():
    actual = np.array([0.01, 0.02, 0.03])
    assert pinball_loss(actual, actual, 0.9) == 0.0
    metrics = interval_scores(
        actual,
        np.array([0.005, 0.015, 0.025]),
        np.array([0.015, 0.025, 0.035]),
        lower_quantile=0.5,
        upper_quantile=0.9,
    )
    assert metrics["nominal_coverage"] == 0.40
    assert metrics["empirical_coverage"] == 1.0
    assert metrics["interval_width"] > 0


def test_asymmetric_quantile_interval_uses_bound_specific_proper_penalties():
    actual = np.array([0.0, 1.5, 3.0])
    lower = np.array([1.0, 1.0, 1.0])
    upper = np.array([2.0, 2.0, 2.0])
    metrics = interval_scores(actual, lower, upper, lower_quantile=0.5, upper_quantile=0.9)
    symmetric_winkler = np.mean((upper - lower) + (2 / (1 - 0.4)) * np.array([1.0, 0.0, 1.0]))
    # The lower miss costs 1 / 0.50 and the upper miss costs 1 / (1 - 0.90),
    # so this intentionally differs from a symmetric 40%-coverage formula.
    assert np.isclose(metrics["winkler_score"], 5.0)
    assert metrics["winkler_score"] != symmetric_winkler


def test_crisis_period_mask_uses_only_predeclared_historical_windows():
    dates = pd.Series(pd.to_datetime(["2008-06-30", "2015-06-30", "2020-06-30", "2023-06-30"]))
    assert _crisis_period_mask(dates).tolist() == [True, False, True, True]


def test_nonconverged_bayesian_draws_are_excluded_from_comparison():
    diagnostics = {"rhat_max": 1.02, "ess_bulk_min": 99.0, "divergences": 1}
    assert _bayesian_convergence_failure(diagnostics, {"rhat_max": 1.01, "ess_bulk_min": 100, "divergences_ideal": 0})
    assert _bayesian_convergence_failure(
        {"rhat_max": 1.005, "ess_bulk_min": 101.0, "divergences": 0},
        {"rhat_max": 1.01, "ess_bulk_min": 100, "divergences_ideal": 0},
    ) is None


def test_oos_windows_remain_the_approved_2005_expanding_windows():
    root = Path(__file__).resolve().parents[1]
    windows = load_model_specs(root)["oos_windows"]
    assert windows == [
        {"train_start": "2005-01-01", "train_end": "2011-12-31", "test_start": "2012-01-01", "test_end": "2016-12-31"},
        {"train_start": "2005-01-01", "train_end": "2016-12-31", "test_start": "2017-01-01", "test_end": "2019-12-31"},
        {"train_start": "2005-01-01", "train_end": "2019-12-31", "test_start": "2020-01-01", "test_end": "2021-12-31"},
        {"train_start": "2005-01-01", "train_end": "2021-12-31", "test_start": "2022-01-01", "test_end": "2025-12-31"},
    ]


def test_recursive_cre_q90_status_is_derived_from_all_prespecified_windows():
    summary = pd.DataFrame({
        "pseudo_window": ["GFC", "COVID", "High_Rate_CRE"],
        "model": ["quantile_0.9"] * 3,
        "segment": ["CRE"] * 3,
        "n": [443, 241, 457],
        "pinball_loss": [0.0892845886, 0.0110109205, 0.0634617323],
        "exceedance_count": [296, 1, 63],
        "empirical_exceedance_rate": [296 / 443, 1 / 241, 63 / 457],
        "nominal_exceedance_rate": [0.1] * 3,
    })
    statement = recursive_cre_q90_calibration_statement(summary, [
        {"name": "GFC"}, {"name": "COVID"}, {"name": "High_Rate_CRE"},
    ])
    assert "not historically calibrated" in statement
    assert "GFC: severe undercoverage (296/443 exceedances, 66.8% observed versus 10.0% nominal; pinball loss 0.08928)" in statement
    assert "COVID: extreme overprediction (1/241 exceedances, 0.4% observed versus 10.0% nominal; pinball loss 0.01101)" in statement
    assert "2022+ high-rate/CRE: instability/mild undercoverage (63/457 exceedances, 13.8% observed versus 10.0% nominal; pinball loss 0.06346)" in statement
    assert "pre-specified downstream tail model" in statement


def test_figures_include_explicit_bayesian_fallback_when_no_posterior_exists(tmp_path: Path):
    prediction = pd.DataFrame({
        "model": ["dynamic_fe", "quantile_0.75", "quantile_0.9"],
        "report_date": pd.to_datetime(["2020-03-31"] * 3),
        "nco_rate": [0.02] * 3,
        "prediction": [0.015, 0.02, 0.03],
    })
    stress = pd.DataFrame({
        "pseudo_window": ["GFC", "COVID", "High_Rate_CRE"],
        "model": ["dynamic_fe"] * 3,
        "report_date": pd.to_datetime(["2008-03-31", "2020-03-31", "2022-03-31"]),
        "nco_rate": [0.02, 0.03, 0.04],
        "prediction": [0.01, 0.02, 0.03],
    })
    write_validation_figures(prediction, stress, tmp_path)
    names = {path.name for path in (tmp_path / "outputs" / "validation" / "figures").iterdir()}
    assert names == {
        "fe_mean_vs_actual.png", "quantile_75_90_bands.png", "bayesian_posterior_interval.png",
        "gfc_pseudo_stress.png", "covid_pseudo_stress.png", "high_rate_cre_pseudo_stress.png",
    }
