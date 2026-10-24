"""C&I recursive simulation using the archived per-variable macro timing."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scenarios import MACROS
from .states import LinearState

CONTROL_MAP = {'lagged_noncurrent_ratio': 'npl_rate', 'lagged_allowance_coverage': 'allowance_coverage',
               'lagged_loan_growth': 'loan_growth', 'lagged_tier1_ratio': 'tier1_ratio'}


def propagate(model: LinearState, jump: pd.DataFrame, centers: pd.DataFrame,
              macro_deviations: np.ndarray, credit_shocks: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    paths, horizon, dimensions = macro_deviations.shape
    if dimensions != len(MACROS) or credit_shocks.shape != (paths, horizon, len(jump)) or len(centers) != horizon:
        raise ValueError('simulation shape mismatch')
    if not np.isfinite(macro_deviations).all() or not np.isfinite(credit_shocks).all():
        raise ValueError('nonfinite simulation innovations')
    quarters = pd.DatetimeIndex(centers.quarter)
    if quarters.has_duplicates or not np.all(np.diff(quarters.to_period('Q').astype(int)) == 1):
        raise ValueError('scenario quarters must be contiguous')
    banks = jump.bank_id.astype(str).tolist()
    if len(set(banks)) != len(banks) or not set(banks).issubset(model.intercepts):
        raise ValueError('duplicate or unknown bank in simulation')
    exposure = jump.exposure.to_numpy(float)
    state = np.broadcast_to(jump.nco_rate.to_numpy(float), (paths, len(jump))).copy()
    if not np.isfinite(state).all() or not np.isfinite(exposure).all() or np.any(exposure <= 0):
        raise ValueError('invalid jump-off state or exposure')
    intercept = np.array([model.intercepts[bank] for bank in banks])
    rates = np.empty((paths, horizon, len(jump)))
    for t, (_, row) in enumerate(centers.iterrows()):
        value = np.broadcast_to(intercept, state.shape).copy()
        for term, coefficient in zip(model.predictors, model.coefficients, strict=True):
            if term == 'lagged_nco_rate':
                value += coefficient * state
            elif term in CONTROL_MAP:
                controls = jump[CONTROL_MAP[term]].to_numpy(float)
                if not np.isfinite(controls).all():
                    raise ValueError('incomplete frozen control')
                value += coefficient * controls
            else:
                macro = term.removeprefix('lagged_')
                if macro not in MACROS or term not in row:
                    raise ValueError(f'unsupported or missing macro predictor {term}')
                source_quarter = pd.Timestamp(row[f'{term}_source_quarter'])
                if source_quarter >= row.quarter:
                    raise ValueError('macro source quarter is not prior to target')
                perturbation = np.zeros(paths)
                if source_quarter >= quarters.min():
                    source_position = quarters.get_indexer([source_quarter])[0]
                    if source_position < 0:
                        raise ValueError('macro source quarter unavailable')
                    perturbation = macro_deviations[:, source_position, MACROS.index(macro)]
                value += coefficient * (float(row[term]) + perturbation[:, None])
        state = value + credit_shocks[:, t]
        if not np.isfinite(state).all():
            raise ValueError('nonfinite simulated NCO path')
        rates[:, t] = state
    unfloored = (rates.sum(axis=1) * exposure / 4.)
    floored = (np.maximum(rates, 0).sum(axis=1) * exposure / 4.)
    return rates, floored, unfloored
