"""Training-only calibration and explicitly limited historical holdout diagnostics."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bankstress.modeling import _eligible_frame
from bankstress.tail_validation import _prepare_jump_off_state
from .scenarios import MACROS, contiguous_blocks, sample_blocks, fit_credit_factor, fit_var
from .simulation import CONTROL_MAP, propagate
from .states import LinearState, assert_training_cutoff


def residual_validation(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    intervals = train.groupby('bank_id').residual.quantile([.05, .95]).unstack()
    joined = test.merge(intervals, on='bank_id', validate='many_to_one')
    if joined.empty:
        raise ValueError('no supported holdout residuals')
    return {'heldout_n': len(joined), 'unknown_bank_exclusions': len(test) - len(joined),
            'training_residual_rmse': float(np.sqrt(np.mean(train.residual ** 2))),
            'heldout_rmse': float(np.sqrt(np.mean(joined.residual ** 2))),
            'empirical_90_interval_coverage': float(joined.residual.between(joined[.05], joined[.95]).mean()),
            'empirical_upper95_exceedance': float((joined.residual > joined[.95]).mean())}


def historical_diagnostics(panel: pd.DataFrame, spec: dict, run: Path, output: Path, settings: dict) -> None:
    eligible = _eligible_frame(panel, spec)
    rows, cumulative_rows, macro_rows = [], [], []
    ci = eligible[eligible.segment.eq('CI')]
    macro = pd.read_parquet(run / 'inputs/macro_history.parquet').set_index('report_date')[MACROS]
    original = pd.read_parquet(run / 'fitted/historical_predictions.parquet')
    for window_id, window in enumerate(spec['oos_windows'], 1):
        cutoff = pd.Timestamp(window['train_end'])
        train = ci[ci.evaluation_eligible & ci.target_period.between(pd.Timestamp(window['train_start']), cutoff)].copy()
        assert_training_cutoff(train, cutoff)
        # Forecasting diagnostic for the macro transition, not a calibration
        # claim about the user-specified Fed conditional centers.
        try:
            var, _ = fit_var(macro.loc[macro.index <= cutoff])
            scale, mean, a = np.asarray(var['scale']), np.asarray(var['mean']), np.asarray(var['transition'])
            holdout = macro.loc[macro.index > cutoff].loc[:pd.Timestamp(window['test_end'])]
            previous = macro.shift(1).reindex(holdout.index)
            predicted = (((previous.to_numpy() - mean) / scale) @ a.T + np.asarray(var['intercept'])) * scale + mean
            for j, name in enumerate(MACROS):
                error = holdout[name].to_numpy() - predicted[:, j]
                macro_rows.append({'window': window_id, 'macro': name, 'status': 'EVALUATED_DIAGNOSTIC',
                                   'spectral_radius': var['spectral_radius'], 'n': len(error),
                                   'rmse': float(np.sqrt(np.mean(error ** 2))), 'bias': float(error.mean())})
        except ValueError as exc:
            macro_rows.append({'window': window_id, 'status': 'NOT_EVALUATED', 'reason': str(exc)})
        for model in ('ar', 'dynamic_fe'):
            state = LinearState.load(run / f'fitted/w{window_id}_CI_{model}.json')
            residual_train = train.assign(residual=train.nco_rate - state.predict(train))
            test = original[(original.segment == 'CI') & (original.window == window_id) &
                            (original.model == model)].dropna(subset=['actual']).copy()
            residual_test = test.assign(residual=test.actual - test.prediction)
            rows.append({'window': window_id, 'model': model, 'scope': 'one_step_credit_residual',
                         'calibration_end': str(cutoff.date()), **residual_validation(residual_train, residual_test)})
            # Nine-quarter paths conditional on realized available macro predictors.
            # This diagnoses the credit residual layer, not unconditional macro tails.
            dates = pd.date_range(cutoff + pd.offsets.QuarterEnd(), periods=9, freq='QE')
            base = {'window': window_id, 'model': model, 'scope': 'nine_quarter_credit_conditional_on_realized_macro'}
            if dates[-1] > pd.Timestamp(window['test_end']):
                cumulative_rows.append({**base, 'status': 'NOT_EVALUATED', 'reason': 'heldout window shorter than nine quarters'})
                continue
            try:
                jump, excluded = _prepare_jump_off_state(ci[ci.target_period <= cutoff], cutoff)
                jump = jump[jump.bank_id.isin(state.intercepts) & jump.exposure.notna() & jump.exposure.gt(0)].copy()
                for predictor, control in CONTROL_MAP.items():
                    jump[control] = jump[predictor]
                counts = residual_train.groupby('bank_id').size()
                supported = counts[counts >= settings['minimum_bank_residual_quarters']].index
                original_banks = len(jump)
                jump = jump[jump.bank_id.isin(supported)].sort_values('bank_id').reset_index(drop=True)
                if len(jump) < 2:
                    raise ValueError('too few banks with complete jump-off and calibration support')
                banks = jump.bank_id.tolist()
                residuals = residual_train.pivot(index='target_period', columns='bank_id', values='residual').reindex(columns=banks)
                fitted, factor, idio, _ = fit_credit_factor(residuals, settings['factor_min_bank_fraction'], settings['minimum_bank_residual_quarters'])
                rng = np.random.default_rng(settings['seed'] + window_id)
                n = 2000
                common = sample_blocks(contiguous_blocks(factor.to_frame(), 4), n, 9, rng)[:, :, 0]
                shocks = np.empty((n, 9, len(banks)))
                for j, bank in enumerate(banks):
                    specific = sample_blocks(contiguous_blocks(idio[[bank]], 4), n, 9, rng)[:, :, 0]
                    shocks[:, :, j] = (common * fitted['loadings'][j] + specific) * fitted['scale'][j]
                center = pd.DataFrame({'quarter': dates})
                for term in state.predictors:
                    if term == 'lagged_nco_rate' or term in CONTROL_MAP:
                        continue
                    unique = ci[ci.target_period.isin(dates)][['target_period', term]].dropna().drop_duplicates()
                    if unique.target_period.duplicated().any():
                        raise ValueError('historical macro differs across banks')
                    center[term] = unique.set_index('target_period')[term].reindex(dates).to_numpy()
                    delay = 1 if term in ('lagged_gdp_growth', 'lagged_unemployment_rate') else 2
                    center[f'{term}_source_quarter'] = (dates.to_period('Q') - delay).to_timestamp('Q')
                _, simulated, _ = propagate(state, jump, center, np.zeros((n, 9, 4)), shocks)
                actual = ci[ci.target_period.isin(dates)].pivot(index='target_period', columns='bank_id', values='nco_rate').reindex(index=dates, columns=banks)
                complete = actual.notna().all().to_numpy()
                if not complete.any():
                    raise ValueError('no nine-quarter complete realized bank paths')
                realized = np.maximum(actual.to_numpy()[:, complete], 0).sum(axis=0) * jump.exposure.to_numpy()[complete] / 4
                lower, upper = np.quantile(simulated[:, complete], [.05, .95], axis=0, method='inverted_cdf')
                cumulative_rows.append({**base, 'status': 'EVALUATED_DIAGNOSTIC', 'calibration_end': str(cutoff.date()),
                                        'paths': n, 'generated_banks': len(banks), 'scored_banks': int(complete.sum()),
                                        'jump_off_exclusions': excluded, 'residual_support_exclusions': original_banks - len(jump),
                                        'missing_actual_path_exclusions': int((~complete).sum()),
                                        'bank_90_interval_coverage': float(((realized >= lower) & (realized <= upper)).mean()),
                                        'bank_upper95_exceedance': float((realized > upper).mean()),
                                        'actual_loss_thousands': float(realized.sum()),
                                        'simulated_mean_scored_universe_thousands': float(simulated[:, complete].sum(axis=1).mean())})
            except ValueError as exc:
                cumulative_rows.append({**base, 'status': 'NOT_EVALUATED', 'reason': str(exc)})
    pd.DataFrame(rows).to_csv(output / 'historical_diagnostics.csv', index=False)
    pd.DataFrame(cumulative_rows).to_csv(output / 'historical_nine_quarter_diagnostics.csv', index=False)
    pd.DataFrame(macro_rows).to_csv(output / 'historical_macro_diagnostics.csv', index=False)
