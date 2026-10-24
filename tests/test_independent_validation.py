import json

import numpy as np
import pandas as pd
import pytest


def forecasts():
    return pd.DataFrame({
        'bank_id': ['a', 'b', 'c'], 'segment': ['CI'] * 3,
        'forecast_origin': pd.to_datetime(['2020-02-14'] * 3),
        'target_period': pd.to_datetime(['2020-03-31'] * 3),
        'window': [1] * 3, 'model': ['ar'] * 3, 'tau': [np.nan] * 3,
        'version': ['ORIGINAL'] * 3, 'actual': [1., 3., np.nan],
        'prediction': [0., 5., 2.],
    })


def test_independent_scores_use_available_actuals_and_actual_minus_prediction():
    from bankstress.modelrisk.scoring import score_forecasts
    scores, coverage = score_forecasts(forecasts())
    row = scores.query('window == 1').iloc[0]
    assert row.rmse == pytest.approx(np.sqrt(2.5))
    assert row.mae == 1.5
    assert row.bias == -.5
    assert row.n == 2
    assert coverage.generated_n.iloc[0] == 3
    assert coverage.missing_actual_n.iloc[0] == 1


def test_pinball_and_interval_have_correct_nominal_coverage():
    from bankstress.modelrisk.scoring import score_forecasts
    low = forecasts().assign(model='quantile', tau=.5, prediction=[0., 2., 1.])
    high = low.assign(tau=.9, prediction=[2., 4., 3.])
    scores, _ = score_forecasts(pd.concat([low, high]))
    row = scores.query('window == 1 and tau == .9').iloc[0]
    assert row.pinball_loss == pytest.approx(.1)
    assert row.exceedance_rate == 0
    assert row.band_coverage == 1
    assert row.nominal_band_coverage == pytest.approx(.4)


def test_duplicate_conflicting_actual_and_infinite_prediction_rejected():
    from bankstress.modelrisk.scoring import score_forecasts
    data = forecasts()
    with pytest.raises(ValueError, match='duplicate'):
        score_forecasts(pd.concat([data, data]))
    other = data.assign(model='ridge', actual=[2., 3., np.nan])
    with pytest.raises(ValueError, match='actual'):
        score_forecasts(pd.concat([data, other]))
    with pytest.raises(ValueError, match='finite'):
        score_forecasts(data.assign(prediction=np.inf))


def test_common_scoring_keys_and_pooled_observation_weighting():
    from bankstress.modelrisk.scoring import score_forecasts
    ar = forecasts()
    other = ar.iloc[:1].assign(model='ridge')
    scores, coverage = score_forecasts(pd.concat([ar, other]))
    assert set(scores.n) == {1}
    assert coverage.query("model == 'ar'").common_key_excluded_n.iloc[0] == 1


def test_sealed_bundle_rejects_tampering_and_path_escape(tmp_path):
    from bankstress.modelrisk.bundle import seal_bundle, verify_bundle
    (tmp_path / 'data.txt').write_text('original')
    seal_bundle(tmp_path, {'run_id': 'test'})
    verify_bundle(tmp_path)
    (tmp_path / 'data.txt').write_text('changed')
    with pytest.raises(ValueError, match='hash'):
        verify_bundle(tmp_path)
    payload = json.loads((tmp_path / 'manifest.json').read_text())
    payload['files']['../outside'] = '0' * 64
    (tmp_path / 'manifest.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='path'):
        verify_bundle(tmp_path)


def test_frozen_linear_state_roundtrip_unknown_bank_and_feature_order(tmp_path):
    from bankstress.modelrisk.states import LinearState
    state = LinearState(['x', 'z'], [2., -1.], {'a': 3.}, 'CI', 'RECONSTRUCTED')
    path = tmp_path / 'model.json'
    state.save(path)
    loaded = LinearState.load(path)
    data = pd.DataFrame({'bank_id': ['a'], 'z': [4.], 'x': [5.]})
    assert loaded.predict(data).tolist() == [9.]
    with pytest.raises(ValueError, match='unknown bank'):
        loaded.predict(data.assign(bank_id='new'))


def test_training_cutoff_rejects_future_rows():
    from bankstress.modelrisk.states import assert_training_cutoff
    data = pd.DataFrame({'target_period': pd.to_datetime(['2025-12-31', '2026-03-31'])})
    with pytest.raises(ValueError, match='cutoff'):
        assert_training_cutoff(data, '2025-12-31')


def test_no_common_scoring_rows_are_reported_not_silently_removed():
    from bankstress.modelrisk.scoring import score_forecasts
    a = forecasts().iloc[:1]
    b = forecasts().iloc[1:2].assign(model='ridge')
    scores, _ = score_forecasts(pd.concat([a, b]))
    assert len(scores) == 4  # two models, window and pooled
    assert scores.n.eq(0).all()
    assert scores.rmse.isna().all()


def test_linked_bundle_rejects_valid_but_wrong_parent(tmp_path):
    from bankstress.modelrisk.bundle import seal_bundle, verify_linked
    from bankstress.artifacts import sha256_file
    parent, child = tmp_path / 'inputs', tmp_path / 'fitted'
    parent.mkdir(); child.mkdir()
    (parent / 'data.txt').write_text('a')
    seal_bundle(parent, {})
    (child / 'state.txt').write_text('b')
    seal_bundle(child, {'input_manifest_sha256': '0' * 64})
    with pytest.raises(ValueError, match='lineage'):
        verify_linked(child, parent, 'input_manifest_sha256')
