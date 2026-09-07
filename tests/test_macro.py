import pandas as pd
import pytest

from bankstress.macro import _quarterly, validate_macro_forecast_alignment, validate_release_calendar


def test_monthly_mean_and_growth_transform_are_deterministic():
    levels = pd.DataFrame({"observation_date": pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30", "2020-05-31", "2020-06-30"]), "value": [100, 100, 100, 110, 110, 110]})
    result = _quarterly(levels, "quarterly_mean", "qoq_pct_change")
    assert pd.isna(result.iloc[0].value)
    assert result.iloc[1].value == pytest.approx(10.0)


def test_reported_yoy_growth_is_not_percentage_changed_again():
    reported_growth = pd.DataFrame({"observation_date": pd.to_datetime(["2020-01-01", "2020-04-01"]), "value": [-8.0, -6.5]})
    result = _quarterly(reported_growth, "quarter_end", "reported_yoy_pct_change")
    assert result.value.tolist() == pytest.approx([-8.0, -6.5])


def test_release_calendar_rejects_future_observation_or_availability():
    origins = pd.DatetimeIndex([pd.Timestamp("2010-03-31")])
    valid = pd.DataFrame({"release_date": [pd.Timestamp("2010-03-31")], "observation_date": [pd.Timestamp("2010-02-28")]})
    validate_release_calendar(valid, origins)
    future = valid.assign(observation_date=pd.Timestamp("2010-04-30"))
    with pytest.raises(ValueError, match="future"):
        validate_release_calendar(future, origins)


def test_same_quarter_release_must_be_visible_by_forecast_origin():
    calendar = pd.DataFrame({"series_id": ["X"], "observation_date": [pd.Timestamp("2020-03-31")], "release_date": [pd.Timestamp("2020-04-30")]})
    contract = pd.DataFrame({"report_period": [pd.Timestamp("2020-06-30")], "available_at": [pd.Timestamp("2020-08-14")], "forecast_origin": [pd.Timestamp("2020-08-14")], "target_period": [pd.Timestamp("2020-09-30")]})
    audit = validate_macro_forecast_alignment(calendar, contract)
    assert audit.available_by_forecast_origin.all()
    assert audit.observation_not_future.all()


def test_future_macro_release_is_invisible():
    calendar = pd.DataFrame({"series_id": ["X"], "observation_date": [pd.Timestamp("2020-09-30")], "release_date": [pd.Timestamp("2020-10-30")]})
    contract = pd.DataFrame({"report_period": [pd.Timestamp("2020-06-30")], "available_at": [pd.Timestamp("2020-08-14")], "forecast_origin": [pd.Timestamp("2020-08-14")], "target_period": [pd.Timestamp("2020-09-30")]})
    assert validate_macro_forecast_alignment(calendar, contract).empty
