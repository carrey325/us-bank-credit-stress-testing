"""Run orchestration; independent evaluators consume sealed producer artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from bankstress.artifacts import sha256_file
from .bundle import code_record, freeze_archive, new_run, seal_bundle, verify_bundle, verify_linked, write_json
from .fitting import fit_oos, reconstruction_differences
from .remediation import repair_crossing, retest_crossing
from .scoring import normalize_historical, score_forecasts


def load_settings(root: Path, config: Path | None = None) -> dict:
    settings = yaml.safe_load((config or root / 'configs/model_risk.yaml').read_text(encoding='utf-8'))
    if settings.get('schema_version') != 1:
        raise ValueError('unsupported model risk configuration')
    if settings['horizon'] != 9 or settings['block_length'] != 4:
        raise ValueError('v1 requires nine quarters and four-quarter bootstrap blocks')
    return settings


def validate_run(root: Path, archive: Path, run_id: str, settings: dict) -> Path:
    run = new_run(root / settings['output_root'], run_id)
    try:
        write_json(run / 'settings.json', settings)
        freeze_archive(archive, run / 'inputs', root, {'run_id': run_id, 'cutoff': settings['cutoff']})
        verify_bundle(run / 'inputs')
        historical = normalize_historical(run / 'inputs')
        panel = pd.read_parquet(run / 'inputs/model_panel.parquet')
        spec = yaml.safe_load((run / 'inputs/model_specs.yaml').read_text())
        if max(pd.Timestamp(w['train_end']) for w in spec['oos_windows']) > pd.Timestamp(settings['cutoff']):
            raise ValueError('OOS training window exceeds configured cutoff')
        reconstructed, challengers = fit_oos(panel, spec, run / 'fitted', settings['seed'])
        historical.to_parquet(run / 'fitted/historical_predictions.parquet', index=False)
        reconstructed.to_parquet(run / 'fitted/reconstructed_predictions.parquet', index=False)
        challengers.to_parquet(run / 'fitted/challenger_predictions.parquet', index=False)
        differences = reconstruction_differences(historical, reconstructed)
        differences.to_parquet(run / 'fitted/reconstruction_differences.parquet', index=False)
        seal_bundle(run / 'fitted', {'run_id': run_id, **code_record(root),
                                     'input_manifest_sha256': sha256_file(run / 'inputs/manifest.json')})
        verify_linked(run / 'fitted', run / 'inputs', 'input_manifest_sha256')
        result = run / 'validation'
        result.mkdir()
        # Reload sealed outputs, not in-memory estimator predictions.
        original = pd.read_parquet(run / 'fitted/historical_predictions.parquet')
        new = pd.read_parquet(run / 'fitted/challenger_predictions.parquet')
        historical_metrics, historical_coverage = score_forecasts(original)
        scores, coverage = score_forecasts(pd.concat([original, new], ignore_index=True))
        historical_metrics.to_csv(result / 'historical_scores.csv', index=False)
        historical_coverage.to_csv(result / 'historical_coverage.csv', index=False)
        scores.to_csv(result / 'challenger_scores.csv', index=False)
        coverage.to_csv(result / 'coverage.csv', index=False)
        summary = {'run_id': run_id, 'integrity_status': 'PASS',
                   'historical_prediction_rows': len(original), 'challenger_prediction_rows': len(new),
                   'reconstruction_compared_rows': len(differences),
                   'reconstruction_mismatch_rows': int((~differences.within_tolerance).sum()),
                   'reconstruction_max_absolute_difference': float(differences.difference.abs().max()),
                   'predictive_adequacy': 'DIAGNOSTIC_NOT_AUTOMATICALLY_APPROVED',
                   'stress_challenger_authorizations_added': 0}
        write_json(result / 'summary.json', summary)
        pooled = scores[scores.window.eq(0)]
        report = [
            '# Independent model validation', '',
            f'Run: `{run_id}`. Frozen historical forecasts and reconstructed fits are separate objects.', '',
            f'Integrity: PASS. Reconstruction mismatches: {summary["reconstruction_mismatch_rows"]}; '
            f'maximum absolute difference: {summary["reconstruction_max_absolute_difference"]:.8g}.', '',
            '## Method and independence', '',
            'The scorer reads sealed forecasts and never invokes fitting or legacy score functions. '
            'Bias is actual minus prediction. Each estimand/window/version uses identical scoring keys across models. '
            'Pooled scores concatenate observations. Missing targets are excluded only from scoring. '
            'Q50–Q90 is a 40% band. Zero exceedances do not establish calibration.', '',
            'Ridge and gradient boosting use three expanding training-only folds, keeping whole quarters together. '
            'Scaling and bank encoding are fitted inside each fold. Selection uses squared error for means and '
            'pinball loss for quantiles. Unknown-bank exclusions and the full candidate audit are retained.', '',
            '## Pooled results', '', '```csv', pooled.to_csv(index=False).strip(), '```', '',
            '## Use restrictions', '',
            'Integrity PASS is not predictive approval. AR remains the mean benchmark; C&I dynamic FE retains '
            'its limited-challenger status. New challengers are OOS diagnostics only. Historical mean-model '
            'negative findings, final-vintage limitations and selected-bank coverage remain in force. '
            'No statistical significance, regulatory approval or capital forecast is asserted.', '',
            'Evidence: historical_scores.csv, challenger_scores.csv, coverage.csv; frozen tuning and '
            'prediction_support tables; row-level reconstruction_differences.parquet.',
        ]
        (result / 'report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
        seal_bundle(result, {'run_id': run_id, 'fitted_manifest_sha256': sha256_file(run / 'fitted/manifest.json')})
        write_json(run / 'status.json', {'validation': 'PASS'})
        return run
    except Exception as exc:
        write_json(run / 'status.json', {'validation': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'})
        raise


def remediation_run(run: Path, expected: int = 507) -> Path:
    verify_bundle(run / 'inputs')
    verify_linked(run / 'fitted', run / 'inputs', 'input_manifest_sha256')
    output = run / 'remediation'
    output.mkdir(exist_ok=False)
    try:
        historical = pd.read_parquet(run / 'fitted/historical_predictions.parquet')
        raw = historical[historical.version.eq('PRE_REARRANGEMENT')].copy()
        repaired, affected = repair_crossing(raw)
        raw.to_parquet(output / 'before.parquet', index=False)
        repaired.to_parquet(output / 'after.parquet', index=False)
        affected.to_parquet(output / 'affected_keys.parquet', index=False)
        # Retest from written artifacts, independent of the repair return object.
        retest = retest_crossing(pd.read_parquet(output / 'before.parquet'), pd.read_parquet(output / 'after.parquet'))
        if retest['before_crossing_rows'] != expected:
            raise ValueError(f'historical crossing count differs from frozen contract: {retest["before_crossing_rows"]} != {expected}')
        retained = historical[historical.version.eq('POST_REARRANGEMENT')]
        diff = reconstruction_differences(retained, repaired)
        if not diff.within_tolerance.all():
            raise ValueError('independent rearrangement differs from retained historical repair')
        scores, coverage = score_forecasts(pd.concat([raw, repaired], ignore_index=True))
        scores.to_csv(output / 'before_after_scores.csv', index=False)
        coverage.to_csv(output / 'coverage.csv', index=False)
        grouped = affected.groupby(['window', 'segment', 'model']).agg(
            crossing_rows=('crossed', 'sum'), max_adjustment=('max_absolute_adjustment', 'max')).reset_index()
        diagnostics = pd.read_csv(run / 'inputs/quantile_diagnostics.csv')
        diagnostics = diagnostics.rename(columns={'model_family': 'model'})
        root_cause = diagnostics.merge(grouped, on=['window', 'segment', 'model'], how='left', validate='many_to_one')
        reconstructed_designs = pd.DataFrame(json.loads((run / 'fitted/catalog.json').read_text()))
        reconstructed_designs = reconstructed_designs[reconstructed_designs.model.isin(['ar_quantile', 'dynamic_quantile'])]
        root_cause = root_cause.merge(reconstructed_designs[
            ['window', 'segment', 'model', 'tau', 'design_rank', 'design_columns', 'design_condition_number']],
            on=['window', 'segment', 'model', 'tau'], how='left', validate='one_to_one')
        root_cause['design_diagnostic_provenance'] = 'RECONSTRUCTED_FIT_NOT_ORIGINAL_OBJECT'
        root_cause.to_csv(output / 'root_cause_diagnostics.csv', index=False)
        finding = {'finding_id': 'MRM-QC-001', 'finding': 'Crossed one-step conditional quantiles',
                   'source_sha256': sha256_file(run / 'inputs/quantile_predictions.parquet'),
                   'remediation_owner': 'model-development workflow', 'retest_owner': 'independent structural verifier',
                   'independence_limit': 'Software/process separation, not separate human institutional validation',
                   'observed_actuals_used_for_repair': False, **retest}
        write_json(output / 'finding.json', finding)
        (output / 'report.md').write_text(
            '# Quantile crossing: finding, root cause, remediation and retest\n\n'
            f'Finding MRM-QC-001: {retest["before_crossing_rows"]} model-family/window/segment prediction rows crossed. '
            'Each row is counted once, not once per quantile.\n\n'
            'Confirmed root cause: separately fitted quantiles impose no joint monotonicity constraint. '
            'Convergence, iteration counts, feature counts and training support are retained in '
            'root_cause_diagnostics.csv; association is not evidence of a numerical root cause.\n\n'
            'Remediation: existing row-wise rearrangement. Targets are not used. Raw forecasts are retained.\n\n'
            'Independent retest: complete quantile vectors, identical keys and actuals, identical per-row '
            'value multisets, zero remaining crossings, and agreement with the historical repaired output. '
            'Structural finding CLOSED. Predictive performance and calibration remain separate open diagnostics.\n\n'
            'See before_after_scores.csv for pinball, exceedance and band coverage, affected_keys.parquet '
            'for changes, and finding.json for evidence hashes. This is independent software verification, '
            'not a claim of organizationally independent regulatory validation.\n', encoding='utf-8')
        seal_bundle(output, {'input_manifest_sha256': sha256_file(run / 'inputs/manifest.json')})
        return output
    except Exception as exc:
        write_json(output / 'failure.json', {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'})
        raise
