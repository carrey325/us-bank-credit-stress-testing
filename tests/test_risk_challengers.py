import numpy as np
import pandas as pd
import pytest


def training_panel():
    rows = []
    for j, date in enumerate(pd.date_range('2010-03-31', periods=24, freq='QE')):
        for bank in ['a', 'b']:
            x = (j % 5) / 100
            rows.append({'bank_id': bank, 'segment': 'CI', 'target_period': date,
                         'forecast_origin': date - pd.Timedelta(days=45), 'x': x,
                         'nco_rate': 2 * x + (bank == 'b') * .01})
    return pd.DataFrame(rows)


def test_temporal_splits_keep_quarters_together_and_never_use_future():
    from bankstress.modelrisk.challengers import temporal_splits
    frame = training_panel()
    splits = temporal_splits(frame)
    assert len(splits) == 3
    for train, validation in splits:
        assert frame.iloc[train].target_period.max() < frame.iloc[validation].target_period.min()
        assert len(validation) % 2 == 0


def test_ridge_and_tree_states_replay_and_ignore_column_order(tmp_path):
    from bankstress.modelrisk.challengers import fit_challenger, load_challenger
    frame = training_panel()
    for family, tau in [('ridge', None), ('gradient_boosting', None), ('gradient_boosting', .9)]:
        fit, audit = fit_challenger(frame, ['x'], family, tau, seed=772)
        assert len(audit) >= 3
        path = tmp_path / f'{family}_{tau}.joblib'
        fit.save(path)
        restored = load_challenger(path)
        np.testing.assert_array_equal(fit.predict(frame), restored.predict(frame[frame.columns[::-1]]))
        with pytest.raises(ValueError, match='unknown bank'):
            restored.predict(frame.assign(bank_id='unknown'))


def test_inner_validation_outcome_does_not_enter_training_scaler():
    from bankstress.modelrisk.challengers import temporal_splits
    data = training_panel()
    train, validation = temporal_splits(data)[0]
    assert set(train).isdisjoint(validation)
    assert max(train) < min(validation)


def test_reconstructed_fe_state_matches_existing_estimator():
    from bankstress.modeling import _fit_entity_fe, _predict_entity_fe
    from bankstress.modelrisk.states import from_fe
    data = training_panel()
    fitted = _fit_entity_fe(data, 'nco_rate', ['x'])
    state = from_fe(fitted, 'CI')
    np.testing.assert_allclose(state.predict(data), _predict_entity_fe(fitted, data, 'nco_rate').prediction, atol=1e-14)


def test_rank_deficient_design_is_explicit_diagnostic_not_finite_condition_claim():
    from bankstress.modelrisk.states import design_diagnostics
    matrix = np.column_stack([np.ones(4), np.arange(4), 2*np.arange(4)])
    info = design_diagnostics(matrix)
    assert info['design_rank'] == 2
    assert info['design_columns'] == 3
    assert info['design_condition_number'] is None
