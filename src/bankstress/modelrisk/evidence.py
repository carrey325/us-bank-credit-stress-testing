"""Verify local full runs and export only compact, hash-bound public evidence."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from bankstress.artifacts import sha256_file
from .bundle import seal_bundle, verify_bundle, verify_linked
from .scoring import score_forecasts
from .remediation import retest_crossing


def verify_run(run: Path, stochastic: str | None = None) -> dict:
    verify_linked(run / 'fitted', run / 'inputs', 'input_manifest_sha256')
    verify_linked(run / 'validation', run / 'fitted', 'fitted_manifest_sha256')
    historical = pd.read_parquet(run / 'fitted/historical_predictions.parquet')
    challengers = pd.read_parquet(run / 'fitted/challenger_predictions.parquet')
    for filename, forecasts in [('historical_scores.csv', historical),
                                ('challenger_scores.csv', pd.concat([historical, challengers], ignore_index=True))]:
        recomputed, _ = score_forecasts(forecasts)
        saved = pd.read_csv(run / 'validation' / filename)
        # Numeric CSV serialization is allowed machine precision, not material score changes.
        pd.testing.assert_frame_equal(saved, recomputed, check_dtype=False, rtol=1e-10, atol=1e-12)
    if (run / 'remediation').exists():
        verify_linked(run / 'remediation', run / 'inputs', 'input_manifest_sha256')
        observed = retest_crossing(pd.read_parquet(run / 'remediation/before.parquet'),
                                  pd.read_parquet(run / 'remediation/after.parquet'))
        recorded = json.loads((run / 'remediation/finding.json').read_text())
        if any(recorded[key] != value for key, value in observed.items()):
            raise ValueError('remediation retest differs from recorded finding')
    if stochastic is not None:
        if not stochastic.replace('_', '').replace('-', '').isalnum():
            raise ValueError('invalid stochastic directory')
        verify_linked(run / stochastic, run / 'inputs', 'input_manifest_sha256')
        risk = pd.read_csv(run / stochastic / 'risk_summary.csv')
        from .risk import empirical_tail
        for (model, scenario), rows in risk.groupby(['model', 'scenario']):
            cumulative = pd.read_parquet(run / stochastic / f'{model}_{scenario}_cumulative.parquet')
            for variant, column in [('floored', 'cumulative_loss_thousands'), ('unfloored', 'cumulative_unfloored_loss_thousands')]:
                portfolio = cumulative.groupby('path_id')[column].sum().to_numpy()
                for row in rows[(rows.bank_id == 'PORTFOLIO') & (rows.variant == variant)].itertuples():
                    var, es = empirical_tail(portfolio, row.alpha)
                    import numpy as np
                    np.testing.assert_allclose([row.mean, row.var, row.es], [portfolio.mean(), var, es], rtol=1e-10, atol=1e-6)
    return {'integrity_status': 'PASS', 'run_id': run.name, 'stochastic': stochastic}


def export_evidence(run: Path, destination: Path, stochastic: str) -> Path:
    verify_run(run, stochastic)
    destination.mkdir(parents=True, exist_ok=False)
    sources = {
        'validation_summary.json': 'validation/summary.json',
        'historical_scores.csv': 'validation/historical_scores.csv',
        'challenger_scores.csv': 'validation/challenger_scores.csv',
        'scoring_coverage.csv': 'validation/coverage.csv',
        'prediction_support.csv': 'fitted/prediction_support.csv',
        'challenger_tuning.csv': 'fitted/tuning.csv',
        'crossing_finding.json': 'remediation/finding.json',
        'crossing_scores.csv': 'remediation/before_after_scores.csv',
        'crossing_diagnostics.csv': 'remediation/root_cause_diagnostics.csv',
        'risk_summary.csv': f'{stochastic}/risk_summary.csv',
        'stochastic_summary.json': f'{stochastic}/summary.json',
        'path_qa.csv': f'{stochastic}/path_qa.csv',
        'deterministic_replay.csv': f'{stochastic}/deterministic_replay.csv',
        'historical_residual_diagnostics.csv': f'{stochastic}/historical_diagnostics.csv',
        'historical_nine_quarter_diagnostics.csv': f'{stochastic}/historical_nine_quarter_diagnostics.csv',
        'historical_macro_diagnostics.csv': f'{stochastic}/historical_macro_diagnostics.csv',
        'simulation_diagnostics.json': f'{stochastic}/calibration/diagnostics.json',
    }
    for target, source in sources.items():
        shutil.copyfile(run / source, destination / target)
    frozen_inputs = verify_bundle(run / 'inputs')
    stochastic_manifest = verify_bundle(run / stochastic)
    seal_bundle(destination, {
        'object_type': 'COMPACT_MODEL_RISK_EVIDENCE', 'run_id': run.name,
        'source_paths': sources, 'input_artifact_hashes': frozen_inputs['files'],
        'source_hashes': stochastic_manifest['source_hashes'], 'packages': stochastic_manifest['packages'],
        'bundle_manifest_hashes': {name: sha256_file(run / name / 'manifest.json')
                                  for name in ('inputs', 'fitted', 'validation', 'remediation', stochastic)},
        'interpretation': 'Conditional research diagnostics; integrity is not predictive approval',
    })
    return destination


def verify_evidence(directory: Path) -> dict:
    manifest = verify_bundle(directory)
    if manifest.get('object_type') != 'COMPACT_MODEL_RISK_EVIDENCE':
        raise ValueError('not a model risk evidence bundle')
    return manifest
