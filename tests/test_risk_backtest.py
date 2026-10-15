import numpy as np
import pandas as pd


def test_holdout_interval_is_calibrated_on_training_residuals_only():
    from bankstress.modelrisk.backtest import residual_validation
    train = pd.DataFrame({'bank_id': ['a'] * 5, 'residual': [-2., -1., 0., 1., 2.]})
    test = pd.DataFrame({'bank_id': ['a', 'a'], 'residual': [0., 100.]})
    row = residual_validation(train, test)
    assert row['heldout_n'] == 2
    assert row['empirical_90_interval_coverage'] == .5
    assert row['empirical_upper95_exceedance'] == .5
    assert row['heldout_rmse'] == np.sqrt(5000.)
