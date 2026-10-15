"""Finding and independent structural retest for existing monotone rearrangement."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import KEYS, validate_forecasts

ROW = ['window', 'model', *KEYS]
TAUS = [.5, .75, .9]


def _matrix(frame: pd.DataFrame) -> pd.DataFrame:
    validate_forecasts(frame)
    if frame.version.nunique() != 1:
        raise ValueError('one prediction version required')
    matrix = frame.pivot(index=ROW, columns='tau', values='prediction')
    if list(matrix.columns) != TAUS or matrix.isna().any().any():
        raise ValueError('complete Q50/Q75/Q90 vectors required; missing keys are not discarded')
    return matrix


def repair_crossing(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = _matrix(raw)
    before = matrix.to_numpy()
    after = np.sort(before, axis=1)
    affected = matrix.index.to_frame(index=False)
    affected['crossed'] = (np.diff(before, axis=1) < 0).any(axis=1)
    affected['max_absolute_adjustment'] = np.abs(after - before).max(axis=1)
    for j, tau in enumerate(TAUS):
        affected[f'raw_q{int(tau*100)}'] = before[:, j]
        affected[f'repaired_q{int(tau*100)}'] = after[:, j]
    repaired_matrix = pd.DataFrame(after, index=matrix.index, columns=matrix.columns)
    values = repaired_matrix.stack().rename('repaired').reset_index()
    repaired = raw.merge(values, on=[*ROW, 'tau'], validate='one_to_one')
    repaired['prediction'] = repaired.pop('repaired')
    repaired['version'] = 'POST_REARRANGEMENT'
    return repaired, affected.loc[affected.crossed].copy()


def retest_crossing(raw: pd.DataFrame, repaired: pd.DataFrame) -> dict:
    before, after = _matrix(raw), _matrix(repaired)
    if not before.index.equals(after.index) or not before.columns.equals(after.columns):
        raise ValueError('repair changed keys')
    # Independently check order and each row's multiset, not the repair function.
    for x, y in zip(before.to_numpy(), after.to_numpy(), strict=True):
        if any(y[j] > y[j+1] for j in range(len(y)-1)):
            raise ValueError('repair still crosses')
        if sorted(x.tolist()) != sorted(y.tolist()):
            raise ValueError('repair changed values rather than rearranging')
    left = raw.set_index([*ROW, 'tau']).actual.sort_index()
    right = repaired.set_index([*ROW, 'tau']).actual.sort_index()
    if not left.equals(right):
        raise ValueError('repair changed actual values')
    return {'before_crossing_rows': int((np.diff(before.to_numpy(), axis=1) < 0).any(axis=1).sum()),
            'after_crossing_rows': int((np.diff(after.to_numpy(), axis=1) < 0).any(axis=1).sum()),
            'complete_vector_n': len(before), 'keys_preserved': True, 'raw_values_preserved': True,
            'structural_status': 'CLOSED', 'predictive_adequacy': 'SEPARATE_OPEN_DIAGNOSTIC',
            'root_cause_confirmed': 'Separately estimated quantiles have no joint monotonicity constraint.',
            'remediation': 'Existing deterministic row-wise increasing rearrangement; no actuals used.'}
