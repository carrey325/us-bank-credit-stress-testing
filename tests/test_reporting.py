from __future__ import annotations

from pathlib import Path
import pandas as pd
import pytest

from bankstress.reporting import conformal_metrics, rolling_residual_intervals, validate_formal_reporting_inputs


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


def test_limited_r4_delivery_has_current_gate_and_null_reason_semantics():
    root = Path(__file__).resolve().parents[1]
    t4 = pd.read_csv(root / "results/evidence/stress_results.csv")
    assert t4.capital_depletion.isna().all()
    assert t4.capital_depletion_reason.str.contains("Unavailable").all()
    assert not ((t4.model == "dynamic_fe") & (t4.segment_scope == "CRE")).any()


def test_full_analytical_delivery_passes_lineage_gate_when_restored():
    root = Path(__file__).resolve().parents[1]
    if not (root / "outputs/reporting/reproducibility_audit.json").exists():
        pytest.skip("Full analytical artifacts are local inputs; see docs/reproduction.md")
    validate_formal_reporting_inputs(root)


def test_formal_reporting_entry_rejects_stale_residual_calibration():
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="does not authorize residual/extra formal inputs"):
        validate_formal_reporting_inputs(
            root,
            additional_formal_artifacts=[root / "outputs/model_risk/rolling_residual_intervals.parquet"],
        )


def test_reproducibility_evidence_does_not_claim_full_end_to_end_rerun():
    root = Path(__file__).resolve().parents[1]
    audit = __import__("json").loads((root / "results/evidence/reproducibility.json").read_text(encoding="utf-8"))
    assert audit["status"] == "PASS"
    assert audit["evidence_classes"]["unit"]["status"] == "PASS"
    assert audit["evidence_classes"]["integration"]["status"] == "PASS"
    assert audit["evidence_classes"]["artifact_consistency"]["status"] == "PASS"
    assert audit["evidence_classes"]["end_to_end"]["status"] == "NOT_RUN"
