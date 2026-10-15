"""Frozen C&I calibration and complete nine-quarter stochastic research runs."""
from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from bankstress.artifacts import sha256_file
from bankstress.modeling import _eligible_frame, _fit_entity_fe
from .bundle import code_record, seal_bundle, verify_bundle, verify_linked, write_json
from .risk import summarize_losses
from .scenarios import MACROS, fit_var, fit_credit_factor, draw_innovations
from .simulation import CONTROL_MAP, propagate
from .states import LinearState, assert_training_cutoff, from_fe


def official_centers(timing: pd.DataFrame) -> dict[str, pd.DataFrame]:
    result = {}
    for scenario in ('baseline', 'severely_adverse'):
        rows = timing[timing.scenario.eq(scenario)].copy()
        rows['quarter'] = pd.to_datetime(rows.quarter)
        rows = rows.sort_values('quarter').reset_index(drop=True)
        expected = pd.date_range('2026-03-31', periods=9, freq='QE')
        if len(rows) != 9 or not pd.DatetimeIndex(rows.quarter).equals(expected):
            raise ValueError('both official scenarios require exactly nine 2026Q1–2028Q1 quarters')
        for column in rows:
            if column.endswith('_source_quarter'):
                rows[column] = pd.to_datetime(rows[column])
        result[scenario] = rows
    return result


def write_paths(path: Path, rates: np.ndarray, jump: pd.DataFrame, quarters: pd.DatetimeIndex) -> None:
    n, h, b = rates.shape
    writer = None
    try:
        for t in range(h):
            values = rates[:, t].reshape(-1)
            exposures = np.tile(jump.exposure.to_numpy(float), n)
            table = pa.Table.from_pandas(pd.DataFrame({
                'path_id': np.repeat(np.arange(n, dtype=np.int32), b),
                'bank_id': np.tile(jump.bank_id.to_numpy(), n),
                'quarter': quarters[t], 'raw_nco_rate': values,
                'quarter_loss_thousands': np.maximum(values, 0) * exposures / 4,
                'quarter_loss_unfloored_thousands': values * exposures / 4,
            }), preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema, compression='zstd')
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()


def _jump_off(archived_paths: pd.DataFrame) -> pd.DataFrame:
    sample = archived_paths[(archived_paths.segment == 'CI') & (archived_paths.model == 'dynamic_fe') &
                            (archived_paths.scenario == 'baseline') & (archived_paths.horizon == 1)].copy()
    if sample.empty or sample.bank_id.duplicated().any():
        raise ValueError('invalid frozen historical C&I jump-off universe')
    jump = sample[['bank_id', 'exposure_thousands', 'starting_tier1_thousands']].rename(columns={'exposure_thousands': 'exposure'})
    jump['bank_id'] = jump.bank_id.astype(str)
    jump['nco_rate'] = sample.input_lagged_nco_rate.to_numpy()
    for predictor, control in CONTROL_MAP.items():
        jump[control] = sample[f'input_{predictor}'].to_numpy()
    return jump.sort_values('bank_id').reset_index(drop=True)


def run_stochastic(root: Path, run: Path, settings: dict, paths: int | None = None,
                   output_name: str = 'stochastic') -> Path:
    if not output_name.replace('_', '').replace('-', '').isalnum():
        raise ValueError('invalid output name')
    if pd.Timestamp(settings['cutoff']) != pd.Timestamp('2025-12-31'):
        raise ValueError('v1 Fed experiment requires the frozen 2025Q4 cutoff')
    n = settings['paths'] if paths is None else paths
    if n < 100:
        raise ValueError('at least 100 Monte Carlo paths required')
    verify_bundle(run / 'inputs')
    verify_linked(run / 'fitted', run / 'inputs', 'input_manifest_sha256')
    output = run / output_name
    output.mkdir(exist_ok=False)
    try:
        calibration = output / 'calibration'
        calibration.mkdir()
        inputs = run / 'inputs'
        panel = pd.read_parquet(inputs / 'model_panel.parquet')
        panel['bank_id'] = panel.bank_id.astype(str)
        spec = yaml.safe_load((inputs / 'model_specs.yaml').read_text())
        eligible = _eligible_frame(panel, spec)
        train = eligible[eligible.segment.eq('CI') & eligible.evaluation_eligible &
                         eligible.target_period.le(pd.Timestamp(settings['cutoff']))].copy()
        assert_training_cutoff(train, settings['cutoff'])
        archived = pd.read_parquet(inputs / 'stress_paths.parquet')
        archived['bank_id'] = archived.bank_id.astype(str)
        jump = _jump_off(archived)
        jump.to_csv(calibration / 'jump_off.csv', index=False)
        banks = jump.bank_id.tolist()
        macro = pd.read_parquet(inputs / 'macro_history.parquet').set_index('report_date')[MACROS]
        macro = macro.loc[macro.index <= pd.Timestamp(settings['cutoff'])]
        var, innovations = fit_var(macro)
        macro_bundle = calibration / 'macro'
        macro_bundle.mkdir()
        write_json(macro_bundle / 'var.json', var)
        innovations.to_parquet(macro_bundle / 'innovations.parquet')
        seal_bundle(macro_bundle, {'cutoff': settings['cutoff'], 'input_manifest_sha256': sha256_file(inputs / 'manifest.json')})
        verify_linked(macro_bundle, inputs, 'input_manifest_sha256')
        var = json.loads((macro_bundle / 'var.json').read_text())
        innovations = pd.read_parquet(macro_bundle / 'innovations.parquet')
        centers = official_centers(pd.read_csv(inputs / 'macro_timing.csv'))
        official = pd.read_parquet(inputs / 'fed_scenarios.parquet').rename(columns={'unemployment': 'unemployment_rate'})
        summaries, qa, diagnostics, parity = [], [], {}, []
        for model, terms in [('ar', ['lagged_nco_rate']), ('dynamic_fe', train.sample_predictors.iloc[0].split('|'))]:
            model_bundle = calibration / model
            model_bundle.mkdir()
            state = from_fe(_fit_entity_fe(train, 'nco_rate', terms), 'CI')
            state.save(model_bundle / 'state.json')
            state = LinearState.load(model_bundle / 'state.json')
            residual_rows = train.assign(residual=train.nco_rate - state.predict(train))
            residuals = residual_rows.pivot(index='target_period', columns='bank_id', values='residual').reindex(columns=banks)
            factor_fit, factor, idio, support = fit_credit_factor(
                residuals, settings['factor_min_bank_fraction'], settings['minimum_bank_residual_quarters'])
            write_json(model_bundle / 'credit_factor.json', factor_fit)
            factor.to_frame().to_parquet(model_bundle / 'factor.parquet')
            idio.to_parquet(model_bundle / 'idiosyncratic.parquet')
            residuals.to_parquet(model_bundle / 'residuals.parquet')
            write_json(model_bundle / 'support.json', support)
            seal_bundle(model_bundle, {'cutoff': settings['cutoff'], 'input_manifest_sha256': sha256_file(inputs / 'manifest.json'),
                                      'jump_off_sha256': sha256_file(calibration / 'jump_off.csv'), **code_record(root)})
            verify_linked(model_bundle, inputs, 'input_manifest_sha256')
            state = LinearState.load(model_bundle / 'state.json')
            factor_fit = json.loads((model_bundle / 'credit_factor.json').read_text())
            factor = pd.read_parquet(model_bundle / 'factor.parquet').credit_factor
            idio = pd.read_parquet(model_bundle / 'idiosyncratic.parquet')
            deviations, shocks, draw_diagnostics = draw_innovations(
                var, innovations, factor_fit, factor, idio, n, settings['horizon'], settings['seed'], settings['block_length'])
            diagnostics[model] = {'residual_support': support, 'sampling': draw_diagnostics,
                                  'residual_calibration': 'centered in-sample fitted residuals; parameter uncertainty excluded'}
            for scenario, center in centers.items():
                zeros_macro, zeros_credit = np.zeros((1, 9, 4)), np.zeros((1, 9, len(jump)))
                deterministic, _, _ = propagate(state, jump, center, zeros_macro, zeros_credit)
                original_model = 'ar_mean' if model == 'ar' else model
                original = archived[(archived.segment == 'CI') & (archived.model == original_model) &
                                    (archived.scenario == scenario)]
                expected = original.pivot(index='quarter', columns='bank_id', values='raw_predicted_nco_rate_decimal_annualized').reindex(index=pd.DatetimeIndex(center.quarter), columns=banks)
                maximum_difference = float(abs(deterministic[0] - expected.to_numpy()).max())
                if not np.allclose(deterministic[0], expected.to_numpy(), atol=1e-10, rtol=1e-8):
                    raise ValueError('zero-shock replay differs from archived deterministic stress')
                parity.append({'model': model, 'scenario': scenario, 'max_absolute_rate_difference': maximum_difference,
                               'zero_shock_replay': 'PASS'})
                rates, losses, unfloored = propagate(state, jump, center, deviations, shocks)
                macro_center = official[official.scenario.eq(scenario)].sort_values('quarter')
                macro_values = deviations + macro_center[MACROS].to_numpy()[None, :, :]
                macro_frame = pd.DataFrame(macro_values.reshape(-1, len(MACROS)), columns=MACROS)
                macro_frame['path_id'] = np.repeat(np.arange(n), 9)
                macro_frame['quarter'] = np.tile(center.quarter.to_numpy(), n)
                macro_frame.to_parquet(output / f'{model}_{scenario}_macro_paths.parquet', index=False)
                write_paths(output / f'{model}_{scenario}_paths.parquet', rates, jump, pd.DatetimeIndex(center.quarter))
                pd.DataFrame({'path_id': np.repeat(np.arange(n), len(banks)), 'bank_id': np.tile(banks, n),
                              'cumulative_loss_thousands': losses.reshape(-1),
                              'cumulative_unfloored_loss_thousands': unfloored.reshape(-1)}).to_parquet(
                                  output / f'{model}_{scenario}_cumulative.parquet', index=False)
                for variant, values in [('floored', losses), ('unfloored', unfloored)]:
                    summary = summarize_losses(values, banks, settings['alphas'], settings['seed'])
                    summaries.append(summary.assign(model=model, scenario=scenario, variant=variant))
                qa.append({'model': model, 'scenario': scenario, 'paths': n, 'banks': len(banks),
                           'floor_rate': float((rates < 0).mean()), 'min_raw_rate': float(rates.min()),
                           'max_raw_rate': float(rates.max()),
                           'sampled_gdp_deviation_sd': float(deviations[:, :, 0].std()),
                           'unemployment_outside_0_100_fraction': float(((macro_values[:, :, 1] < 0) | (macro_values[:, :, 1] > 100)).mean()),
                           'bbb_spread_negative_fraction': float((macro_values[:, :, 2] < 0).mean()),
                           'remaining_correlations_not_modeled': True})
        pd.concat(summaries, ignore_index=True).to_csv(output / 'risk_summary.csv', index=False)
        pd.DataFrame(qa).to_csv(output / 'path_qa.csv', index=False)
        pd.DataFrame(parity).to_csv(output / 'deterministic_replay.csv', index=False)
        write_json(calibration / 'diagnostics.json', diagnostics)
        seal_bundle(calibration, {'cutoff': settings['cutoff'], 'input_manifest_sha256': sha256_file(inputs / 'manifest.json'),
                                  **code_record(root)})
        from .backtest import historical_diagnostics
        historical_diagnostics(panel, spec, run, output, settings)
        write_json(output / 'summary.json', {
            'integrity_status': 'PASS', 'calibration_status': 'LIMITED_NOT_VALIDATED_FOR_PREDICTIVE_USE',
            'risk_use': 'CONDITIONAL_RESEARCH_DISTRIBUTION', 'segment': 'CI',
            'banks': len(banks), 'paths_per_model_scenario': n, 'horizon': 9,
            'seed': settings['seed'], 'macro_spectral_radius': var['spectral_radius'],
            'parameter_uncertainty': False, 'scenario_probabilities': None,
            'units': 'USD thousands', 'residual_dependence': 'common factor plus bank-specific contiguous blocks',
            'limitations': ['final-vintage macro calibration', 'in-sample residual calibration',
                            'remaining idiosyncratic cross-bank correlation not modeled',
                            'static exposure and bank controls', 'dynamic FE limited challenger',
                            'unbounded macro generator can produce inadmissible levels; frequencies in path_qa.csv',
                            'historical cumulative interval coverage is inadequate in some holdout windows',
                            'no regulatory approval or capital forecast']})
        portfolio = pd.concat(summaries).query("bank_id == 'PORTFOLIO' and variant == 'floored'")
        (output / 'report.md').write_text(
            '# Conditional nine-quarter C&I loss distributions\n\n'
            f'{n:,} paths per model and scenario; {len(banks)} banks; 2026Q1–2028Q1; seed {settings["seed"]}. '
            'Amounts are USD thousands. Baseline and severely adverse are separate conditional centers, '
            'not probability-weighted outcomes.\n\n'
            '## Portfolio results\n\n```csv\n' + portfolio.to_csv(index=False) + '```\n\n'
            '## Calibration and interpretation\n\n'
            'Stable standardized VAR(1) deviations start at zero and use four-quarter joint macro/common-credit '
            'innovation blocks. Recorded source quarters determine macro timing. Bank-specific blocks never bridge '
            'missing quarters. Common shocks are shared by every bank. Raw NCO feeds recursion; only loss '
            'aggregation is floored at zero. Portfolio risk is calculated after pathwise aggregation.\n\n'
            'VaR uses the empirical inverse CDF. ES integrates the worst tail probability mass, including '
            'fractional boundary observations. MC standard errors describe simulator sampling error only. '
            'Half-sample sensitivity is included; portfolio VaR/ES MC SE uses 100 path-level bootstrap draws.\n\n'
            '## Limits and retained findings\n\n'
            'Parameters are fixed. Macro history uses final vintages. Centered in-sample residuals may understate '
            'forecast uncertainty; held-out residual diagnostics are provided separately. Factor dependence is '
            'partial: remaining cross-bank idiosyncratic dependence is reported but not simulated. These '
            'limitations can materially affect tail losses. No clipping of macro paths is used.\n\n'
            'AR remains the benchmark; dynamic FE retains limited-challenger status. Neither the simulated '
            'distribution nor passing integrity checks establish predictive calibration, regulatory acceptance '
            'or a capital forecast. See path_qa.csv, deterministic_replay.csv, historical_diagnostics.csv, '
            'calibration/diagnostics.json and the immutable manifests.\n', encoding='utf-8')
        seal_bundle(output, {'input_manifest_sha256': sha256_file(inputs / 'manifest.json'),
                             'settings': settings, 'actual_paths': n, **code_record(root)})
        return output
    except Exception as exc:
        write_json(output / 'failure.json', {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'})
        raise
