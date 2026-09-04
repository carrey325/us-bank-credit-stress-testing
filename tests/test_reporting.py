from __future__ import annotations

import pandas as pd

from bankstress.reporting import conformal_metrics, rolling_residual_intervals


def _oos() -> pd.DataFrame:
    rows = []
    for date_number, date in enumerate(pd.date_range("2012-03-31", periods=5, freq="QE")):
        for bank, error in (("1", 0.01), ("2", -0.01)):
            prediction = 0.02 + date_number * 0.001
            rows.append({"bank_id": bank, "segment": "CRE", "report_date": date, "nco_rate": prediction + error, "prediction": prediction})
    return pd.DataFrame(rows)


def test_rolling_residual_intervals_use_strictly_prior_dates_only():
    intervals = rolling_residual_intervals(_oos(), seed_quarters=2, rolling_quarters=2)
    assert intervals["calibration_end_date"].lt(intervals["report_date"]).all()
    assert set(intervals["method"]) == {"static_residual_bootstrap", "rolling_adaptive_residual_bootstrap"}
    assert intervals["covered"].all()


def test_conformal_metrics_report_required_model_risk_fields():
    intervals = rolling_residual_intervals(_oos(), seed_quarters=2, rolling_quarters=2)
    result = conformal_metrics(intervals)
    assert set(result.columns) >= {"empirical_coverage", "mean_interval_width", "winkler_score", "crisis_underprediction_count", "crisis_underprediction_change_vs_static"}
    assert result["target_coverage"].eq(0.9).all()
