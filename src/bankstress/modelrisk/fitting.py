"""Producer of new frozen states, separate from independent validation."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bankstress.modeling import _eligible_frame, _fit_entity_fe
from bankstress.tail_validation import fit_quantile
from .bundle import write_json
from .challengers import fit_challenger, load_challenger
from .scoring import IDENTITY, KEYS
from .states import LinearState, assert_training_cutoff, from_fe, from_quantile, design_diagnostics


def _rows(test, prediction, model, tau, window, version='ORIGINAL'):
    return test.assign(prediction=prediction, actual=test.nco_rate, model=model,
                       tau=np.nan if tau is None else tau, window=window, version=version)[
                           [*IDENTITY, 'actual', 'prediction']]


def fit_oos(panel: pd.DataFrame, spec: dict, output: Path, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    output.mkdir(parents=True, exist_ok=False)
    panel = panel.copy()
    panel['bank_id'] = panel.bank_id.astype(str)
    eligible = _eligible_frame(panel, spec)
    reconstructed, challengers, catalog, tuning, support = [], [], [], [], []
    for window_id, window in enumerate(spec['oos_windows'], 1):
        for segment in spec['primary_segments']:
            source = eligible[eligible.segment.eq(segment)]
            train = source[source.target_period.between(pd.Timestamp(window['train_start']), pd.Timestamp(window['train_end'])) & source.evaluation_eligible].copy()
            assert_training_cutoff(train, window['train_end'])
            candidates = source[source.target_period.between(pd.Timestamp(window['test_start']), pd.Timestamp(window['test_end'])) & source.prediction_eligible].copy()
            test = candidates[candidates.bank_id.isin(train.bank_id)].copy()
            support.append({'window': window_id, 'segment': segment, 'train_n': len(train),
                            'candidate_prediction_n': len(candidates), 'prediction_n': len(test),
                            'unknown_bank_exclusions': len(candidates) - len(test)})
            terms = source.sample_predictors.iloc[0].split('|')
            for family, predictors in [('ar', ['lagged_nco_rate']), ('dynamic_fe', terms)]:
                state = from_fe(_fit_entity_fe(train, 'nco_rate', predictors), segment)
                name = f'w{window_id}_{segment}_{family}.json'
                state.save(output / name)
                prediction = LinearState.load(output / name).predict(test)
                np.testing.assert_allclose(prediction, state.predict(test), rtol=0, atol=0)
                reconstructed.append(_rows(test, prediction, family, None, window_id))
                catalog.append({'file': name, 'model': family, 'window': window_id, 'segment': segment,
                                'train_start': window['train_start'], 'train_end': window['train_end'],
                                'predictors': predictors, 'banks': sorted(state.intercepts), 'status': 'RECONSTRUCTED'})
            for family, predictors in [('ar_quantile', ['lagged_nco_rate']), ('dynamic_quantile', terms)]:
                matrix = []
                for tau in spec['quantiles']:
                    fitted = fit_quantile(train, predictors, tau, spec['quantile_spec'])
                    if not fitted.converged:
                        raise ValueError(f'quantile reconstruction did not converge: {window_id}/{segment}/{family}/{tau}')
                    state = from_quantile(fitted, segment)
                    name = f'w{window_id}_{segment}_{family}_{tau}.json'
                    state.save(output / name)
                    prediction = LinearState.load(output / name).predict(test)
                    matrix.append(prediction)
                    catalog.append({'file': name, 'model': family, 'tau': tau, 'window': window_id, 'segment': segment,
                                    'train_start': window['train_start'], 'train_end': window['train_end'],
                                    'predictors': predictors, 'banks': sorted(state.intercepts), 'status': 'RECONSTRUCTED',
                                    'iterations': fitted.iterations, 'converged': fitted.converged,
                                    **design_diagnostics(fitted.result.model.exog)})
                    reconstructed.append(_rows(test, prediction, family, tau, window_id, 'PRE_REARRANGEMENT'))
                repaired = np.sort(np.column_stack(matrix), axis=1)
                for j, tau in enumerate(spec['quantiles']):
                    reconstructed.append(_rows(test, repaired[:, j], family, tau, window_id, 'POST_REARRANGEMENT'))
            challengers.append(_rows(test, test.lagged_nco_rate, 'persistence', None, window_id))
            persistence = LinearState(['lagged_nco_rate'], [1.], {bank: 0. for bank in sorted(train.bank_id.unique())}, segment, 'NEW_CHALLENGER')
            name = f'w{window_id}_{segment}_persistence.json'
            persistence.save(output / name)
            catalog.append({'file': name, 'model': 'persistence', 'window': window_id, 'segment': segment,
                            'train_start': window['train_start'], 'train_end': window['train_end'],
                            'predictors': persistence.predictors, 'banks': sorted(persistence.intercepts), 'status': 'NEW_CHALLENGER'})
            tree_quantiles = []
            for family, tau in [('ridge', None), ('gradient_boosting', None),
                                *[('gradient_boosting', t) for t in spec['quantiles']]]:
                fitted, audit = fit_challenger(train, terms, family, tau, seed)
                name = f'w{window_id}_{segment}_{family}_{tau}.joblib'
                fitted.save(output / name)
                prediction = load_challenger(output / name).predict(test)
                np.testing.assert_array_equal(prediction, fitted.predict(test))
                model = family if tau is None else 'gradient_boosting_quantile'
                tuning.extend({'window': window_id, 'segment': segment, 'model': model, 'tau': tau, **row} for row in audit)
                catalog.append({'file': name, 'model': model, 'tau': tau, 'window': window_id, 'segment': segment,
                                'train_start': window['train_start'], 'train_end': window['train_end'],
                                'predictors': terms, 'banks': fitted.banks, 'status': 'NEW_CHALLENGER'})
                challengers.append(_rows(test, prediction, model, tau, window_id,
                                         'ORIGINAL' if tau is None else 'PRE_REARRANGEMENT'))
                if tau is not None:
                    tree_quantiles.append(prediction)
            repaired = np.sort(np.column_stack(tree_quantiles), axis=1)
            for j, tau in enumerate(spec['quantiles']):
                challengers.append(_rows(test, repaired[:, j], 'gradient_boosting_quantile', tau,
                                         window_id, 'POST_REARRANGEMENT'))
    write_json(output / 'catalog.json', catalog)
    pd.DataFrame(tuning).to_csv(output / 'tuning.csv', index=False)
    pd.DataFrame(support).to_csv(output / 'prediction_support.csv', index=False)
    return pd.concat(reconstructed, ignore_index=True), pd.concat(challengers, ignore_index=True)


def reconstruction_differences(original: pd.DataFrame, rebuilt: pd.DataFrame) -> pd.DataFrame:
    joined = original.merge(rebuilt, on=IDENTITY, suffixes=('_historical', '_rebuilt'),
                            how='outer', indicator=True, validate='one_to_one')
    joined['difference'] = joined.prediction_rebuilt - joined.prediction_historical
    joined['within_tolerance'] = joined._merge.eq('both') & np.isclose(
        joined.prediction_rebuilt, joined.prediction_historical, rtol=1e-8, atol=1e-10)
    return joined
