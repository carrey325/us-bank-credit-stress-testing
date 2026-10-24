import pandas as pd
import pytest


def test_verify_evidence_detects_changed_metric(tmp_path):
    from bankstress.modelrisk.evidence import verify_evidence
    from bankstress.modelrisk.bundle import seal_bundle
    pd.DataFrame({'n': [10], 'rmse': [.1]}).to_csv(tmp_path / 'scores.csv', index=False)
    seal_bundle(tmp_path, {'object_type': 'COMPACT_MODEL_RISK_EVIDENCE'})
    assert verify_evidence(tmp_path)['object_type'] == 'COMPACT_MODEL_RISK_EVIDENCE'
    pd.DataFrame({'n': [10], 'rmse': [.2]}).to_csv(tmp_path / 'scores.csv', index=False)
    with pytest.raises(ValueError, match='hash'):
        verify_evidence(tmp_path)
