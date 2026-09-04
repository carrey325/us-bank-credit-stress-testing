from __future__ import annotations

from pathlib import Path

import pandas as pd

from bankstress.reporting import _audit, conformal_metrics, rolling_residual_intervals


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


def test_final_delivery_audit_enforces_table_figure_and_report_semantics():
    root = Path(__file__).resolve().parents[1]
    intervals = pd.read_parquet(root / "outputs" / "model_risk" / "rolling_residual_intervals.parquet")
    tables = pd.read_csv(root / "outputs" / "reporting" / "final_tables_manifest.csv").to_dict("records")
    figures = pd.read_csv(root / "outputs" / "reporting" / "final_figures_manifest.csv").to_dict("records")

    audit = _audit(root, tables, figures, intervals)

    assert audit["status"] == "PASS"
    assert audit["checks"]["required_final_table_schemas_and_semantics"]
    assert audit["checks"]["required_final_figure_semantics"]
    assert audit["checks"]["final_report_has_ten_pages_and_required_positioning"]
    assert audit["checks"]["readme_states_final_delivery_and_model_positioning"]
