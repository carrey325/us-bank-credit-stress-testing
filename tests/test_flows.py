import pandas as pd

from bankstress.transform.flows import quarterize_ytd


def _input(values, dates=None, metric="charge_off"):
    dates = dates or ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"][:len(values)]
    return pd.DataFrame({"bank_id": ["1"] * len(values), "standard_metric": [metric] * len(values), "segment": ["CI"] * len(values), "raw_code": ["X"] * len(values), "report_date": dates, "numeric_value": values})


def test_quarterizes_normal_ytd():
    result = quarterize_ytd(_input([2, 5, 9, 14]))
    assert result.quarterly_value.tolist() == [2, 3, 4, 5]


def test_year_reset_uses_q1_ytd():
    frame = pd.concat([_input([2, 5]), _input([3, 7], ["2025-03-31", "2025-06-30"])])
    result = quarterize_ytd(frame)
    assert result.sort_values("report_date").quarterly_value.tolist() == [2, 3, 3, 4]


def test_missing_prior_returns_missing_reason():
    result = quarterize_ytd(_input([2, 9], ["2024-03-31", "2024-09-30"]))
    assert pd.isna(result.iloc[1].quarterly_value)
    assert result.iloc[1].quarterization_reason == "missing_or_nonconsecutive_prior_ytd"


def test_ytd_decrease_is_retained_and_flagged():
    result = quarterize_ytd(_input([5, 3]))
    assert result.iloc[1].quarterly_value == -2
    assert result.iloc[1].amendment_or_reclass_flag == 1


def test_recovery_exceeding_chargeoff_and_negative_nco_are_allowed():
    chargeoffs = quarterize_ytd(_input([1, 2], metric="charge_off"))
    recoveries = quarterize_ytd(_input([3, 5], metric="recovery"))
    nco = chargeoffs.quarterly_value - recoveries.quarterly_value
    assert nco.tolist() == [-2, -1]
