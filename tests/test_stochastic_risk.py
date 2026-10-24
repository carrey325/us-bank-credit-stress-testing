import numpy as np
import pandas as pd
import pytest


def test_empirical_var_es_fractional_tail_and_ties():
    from bankstress.modelrisk.risk import empirical_tail
    assert empirical_tail(np.array([1., 2., 3., 4.]), .625) == pytest.approx((3., 11/3))
    assert empirical_tail(np.array([0., 0., 10., 10.]), .75) == (10., 10.)
    assert empirical_tail(np.array([5.]), .99) == (5., 5.)
    with pytest.raises(ValueError):
        empirical_tail(np.array([1., np.nan]), .95)


def test_blocks_never_bridge_missing_quarters():
    from bankstress.modelrisk.scenarios import contiguous_blocks, sample_blocks
    index = pd.to_datetime(['2020-03-31', '2020-06-30', '2020-12-31', '2021-03-31', '2021-06-30', '2021-09-30'])
    frame = pd.DataFrame({'x': range(6)}, index=index)
    blocks = contiguous_blocks(frame, 4)
    assert blocks.shape == (1, 4, 1)
    assert blocks[0, :, 0].tolist() == [2, 3, 4, 5]
    a = sample_blocks(blocks, 10, 9, np.random.default_rng(772))
    b = sample_blocks(blocks, 10, 9, np.random.default_rng(772))
    np.testing.assert_array_equal(a, b)
    assert a.shape == (10, 9, 1)


def test_var_stable_fit_and_unstable_calibration_failure():
    from bankstress.modelrisk.scenarios import fit_var
    rng = np.random.default_rng(7)
    x = np.zeros((100, 4))
    for t in range(1, len(x)):
        x[t] = .4 * x[t-1] + rng.normal(size=4)
    frame = pd.DataFrame(x, index=pd.date_range('2000-03-31', periods=100, freq='QE'))
    fitted, innovations = fit_var(frame)
    assert fitted['spectral_radius'] < 1
    assert len(innovations) == 99
    explosive = pd.DataFrame({'x': 1.1 ** np.arange(40)}, index=frame.index[:40])
    with pytest.raises(ValueError, match='unstable'):
        fit_var(explosive)


def test_raw_negative_state_feedback_and_annualized_conversion():
    from bankstress.modelrisk.simulation import propagate
    from bankstress.modelrisk.states import LinearState
    model = LinearState(['lagged_nco_rate', 'lagged_gdp_growth'], [.5, 1.], {'a': 0.}, 'CI', 'RECONSTRUCTED')
    jump = pd.DataFrame({'bank_id': ['a'], 'nco_rate': [-.04], 'exposure': [400.]})
    centers = pd.DataFrame({'quarter': pd.date_range('2026-03-31', periods=2, freq='QE'),
                            'lagged_gdp_growth': [0., 0.],
                            'lagged_gdp_growth_source_quarter': pd.to_datetime(['2025-12-31', '2026-03-31'])})
    rates, loss, unfloored = propagate(model, jump, centers, np.zeros((2, 2, 4)), np.zeros((2, 2, 1)))
    np.testing.assert_allclose(rates[0, :, 0], [-.02, -.01])
    assert loss[0, 0] == 0
    assert unfloored[0, 0] == pytest.approx(-3.)


def test_macro_deviation_uses_recorded_source_quarter_exactly_once():
    from bankstress.modelrisk.simulation import propagate
    from bankstress.modelrisk.states import LinearState
    model = LinearState(['lagged_short_rate'], [1.], {'a': 0.}, 'CI', 'RECONSTRUCTED')
    jump = pd.DataFrame({'bank_id': ['a'], 'nco_rate': [0.], 'exposure': [4.]})
    centers = pd.DataFrame({'quarter': pd.date_range('2026-03-31', periods=3, freq='QE'),
                            'lagged_short_rate': [0., 0., 0.],
                            'lagged_short_rate_source_quarter': pd.to_datetime(['2025-09-30', '2025-12-31', '2026-03-31'])})
    deviations = np.zeros((1, 3, 4)); deviations[0, :, 3] = [2., 4., 8.]
    rates, _, _ = propagate(model, jump, centers, deviations, np.zeros((1, 3, 1)))
    assert rates[0, :, 0].tolist() == [0., 0., 2.]


def test_common_factor_retains_cross_bank_dependency_and_missingness():
    from bankstress.modelrisk.scenarios import fit_credit_factor
    rng = np.random.default_rng(17)
    common = rng.normal(size=40)
    residuals = pd.DataFrame({'a': common + rng.normal(0, .1, 40),
                              'b': 2*common + rng.normal(0, .1, 40)},
                             index=pd.date_range('2010-03-31', periods=40, freq='QE'))
    residuals.iloc[8, 1] = np.nan
    fit, factor, idio, support = fit_credit_factor(residuals, .5, 20)
    assert idio.b.isna().iloc[8]
    assert min(fit['loadings']) > .5
    assert support['bank_observations']['b'] == 39


def test_portfolio_risk_aggregates_paths_before_quantiles():
    from bankstress.modelrisk.risk import summarize_losses
    losses = np.array([[0., 100.], [100., 0.]])
    result = summarize_losses(losses, ['a', 'b'], [.95], seed=772)
    assert result.query("bank_id == 'PORTFOLIO'")['var'].iloc[0] == 100.


def test_bootstrap_population_centering_accounts_for_overlapping_endpoints():
    from bankstress.modelrisk.scenarios import centered_blocks
    # Original series mean is zero, but repeated middle observations bias blocks.
    frame = pd.DataFrame({'x': [-8., 1., 1., 1., 5.]},
                         index=pd.date_range('2020-03-31', periods=5, freq='QE'))
    blocks = centered_blocks(frame, 4)
    assert blocks.shape == (2, 4, 1)
    assert blocks.mean() == pytest.approx(0., abs=1e-15)
    assert blocks[0, 1, 0] - blocks[0, 0, 0] == 9.
