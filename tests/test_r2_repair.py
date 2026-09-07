from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_r2", ROOT / "scripts/run_r2.py")
assert SPEC and SPEC.loader
run_r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_r2)


def _passing_checks() -> dict:
    return {
        "input_run_id": run_r2.R1_RUN_ID,
        "credit_panel_hash": run_r2.R1_PANEL_HASH,
        "transition_audit_hash": run_r2.R1_TRANSITION_HASH,
        "r1_credit_metadata_valid": True,
        "r1_input_run_match": True,
        "r1_credit_panel_hash_match": True,
        "r1_transition_metadata_valid": True,
        "r1_transition_run_match": True,
        "r1_transition_audit_hash_match": True,
        "common_scoring_keys_verified": True,
        "macro_double_lag_count": 0,
        "gap_bridge_count": 0,
        "cre_shock_period_mismatch_count": 0,
        "cre_shock_duplicate_target_count": 0,
        "cre_shock_information_set_mismatch_count": 0,
        "cre_shock_audit_mismatch_count": 0,
        "time_alignment_invalid_count": 0,
        "model_rows": 1,
        "prediction_eligible": 1,
        "evaluation_eligible": 1,
        "macro_carry_comparisons": 1,
        "cre_shock_rows": 1,
        "review_required_rows_preserved": 2,
    }


def test_r2_gate_passes_only_when_all_mandatory_checks_pass():
    summary = _passing_checks()
    assert run_r2._apply_validation_status(summary)
    assert summary["validation_status"] == "PASS"
    assert summary["validation_failures"] == []


@pytest.mark.parametrize(
    ("name", "bad_value"),
    [
        ("macro_double_lag_count", 1),
        ("gap_bridge_count", 1),
        ("cre_shock_period_mismatch_count", 1),
        ("cre_shock_duplicate_target_count", 1),
        ("cre_shock_information_set_mismatch_count", 1),
        ("cre_shock_audit_mismatch_count", 1),
        ("time_alignment_invalid_count", 1),
        ("r1_credit_metadata_valid", False),
        ("r1_input_run_match", False),
        ("r1_credit_panel_hash_match", False),
        ("r1_transition_metadata_valid", False),
        ("r1_transition_run_match", False),
        ("r1_transition_audit_hash_match", False),
        ("common_scoring_keys_verified", False),
        ("review_required_rows_preserved", 1),
        ("macro_carry_comparisons", 0),
    ],
)
def test_r2_gate_fails_closed_for_each_mandatory_invariant(name, bad_value):
    summary = _passing_checks()
    summary[name] = bad_value
    assert not run_r2._apply_validation_status(summary)
    assert summary["validation_status"] == "FAIL"
    assert summary["validation_failures"]


def test_committed_cre_shock_audit_exactly_reconstructs_interaction_input():
    audit_path = ROOT / "outputs/repair/r2/cre_realized_shock_audit.csv"
    audit = pd.read_csv(
        audit_path,
        parse_dates=["target_period", "shock_period"],
        float_precision="round_trip",
    )
    required = {
        "target_period",
        "shock_period",
        "realized_cre_price_growth",
        "information_set",
        "source_series_id",
        "source_file_sha256",
        "source_manifest_sha256",
    }
    assert required.issubset(audit.columns)
    assert not audit.duplicated("target_period").any()
    assert audit.shock_period.eq(audit.target_period).all()
    assert audit.information_set.eq("EX_POST_FINAL_VINTAGE_NOT_FORECAST_ORIGIN_INFORMATION").all()
    metadata = json.loads(
        (ROOT / "outputs/models/cre_interaction/interaction_coefficients.csv.metadata.json").read_text(
            encoding="utf-8"
        )
    )
    inputs = metadata["input_artifact_hashes"]
    audit_key = "outputs/repair/r2/cre_realized_shock_audit.csv"
    assert inputs[audit_key] == run_r2.sha256_file(audit_path)
    assert "data/derived/cre_realized_shock.parquet" not in inputs
