import pandas as pd

from bankstress.io.fdic_financials import _normalise


def test_fdic_noncurrent_ratio_uses_bank_level_denominator():
    result = _normalise([{"CERT": 10, "REPDTE": "20090331", "NCLNLS": 250, "LNLSNET": 5000}])
    assert result.iloc[0].bank_id == "10"
    assert result.iloc[0].report_date == pd.Timestamp("2009-03-31")
    assert result.iloc[0].fdic_noncurrent_ratio == 0.05
