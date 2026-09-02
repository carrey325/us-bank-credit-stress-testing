import pandas as pd
import pytest

from bankstress.macro import _quarterly, validate_release_calendar


def test_monthly_mean_and_growth_transform_are_deterministic():
    levels = pd.DataFrame({"observation_date": pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30", "2020-05-31", "2020-06-30"]), "value": [100, 100, 100, 110, 110, 110]})
    result = _quarterly(levels, "quarterly_mean", "qoq_pct_change")
    assert pd.isna(result.iloc[0].value)
    assert result.iloc[1].value == pytest.approx(10.0)


def test_release_calendar_rejects_future_observation_or_availability():
    origins = pd.DatetimeIndex([pd.Timestamp("2010-03-31")])
    valid = pd.DataFrame({"release_date": [pd.Timestamp("2010-03-31")], "observation_date": [pd.Timestamp("2010-02-28")]})
    validate_release_calendar(valid, origins)
    future = valid.assign(observation_date=pd.Timestamp("2010-04-30"))
    with pytest.raises(ValueError, match="future"):
        validate_release_calendar(future, origins)
