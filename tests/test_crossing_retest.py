import pandas as pd
import pytest


def quantiles():
    return pd.DataFrame({
        'bank_id': ['a'] * 3, 'segment': ['CRE'] * 3,
        'forecast_origin': pd.to_datetime(['2020-02-14'] * 3),
        'target_period': pd.to_datetime(['2020-03-31'] * 3),
        'window': [1] * 3, 'model': ['dynamic_quantile'] * 3,
        'tau': [.5, .75, .9], 'version': ['PRE_REARRANGEMENT'] * 3,
        'actual': [.25] * 3, 'prediction': [.3, .1, .2],
    })


def test_crossing_repair_preserves_raw_and_ignores_actuals():
    from bankstress.modelrisk.remediation import repair_crossing, retest_crossing
    raw = quantiles()
    saved = raw.copy(deep=True)
    repaired, affected = repair_crossing(raw)
    pd.testing.assert_frame_equal(raw, saved)
    assert repaired.prediction.tolist() == [.1, .2, .3]
    assert len(affected) == 1
    changed, _ = repair_crossing(raw.assign(actual=999))
    assert changed.prediction.tolist() == repaired.prediction.tolist()
    result = retest_crossing(raw, repaired)
    assert result['before_crossing_rows'] == 1
    assert result['after_crossing_rows'] == 0
    assert result['structural_status'] == 'CLOSED'


def test_missing_quantile_duplicate_and_incorrect_repair_fail():
    from bankstress.modelrisk.remediation import repair_crossing, retest_crossing
    raw = quantiles()
    with pytest.raises(ValueError, match='complete'):
        repair_crossing(raw.iloc[:2])
    with pytest.raises(ValueError, match='duplicate'):
        repair_crossing(pd.concat([raw, raw.iloc[:1]]))
    repaired, _ = repair_crossing(raw)
    with pytest.raises(ValueError, match='values'):
        retest_crossing(raw, repaired.assign(prediction=[.1, .2, .4]))
    with pytest.raises(ValueError, match='actual'):
        retest_crossing(raw, repaired.assign(actual=.7))
