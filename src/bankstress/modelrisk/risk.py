"""Empirical tail probability mass and path-level portfolio aggregation."""
from __future__ import annotations

import numpy as np
import pandas as pd


def empirical_tail(losses: np.ndarray, alpha: float) -> tuple[float, float]:
    values = np.asarray(losses, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or not 0 < alpha < 1:
        raise ValueError('finite nonempty losses and alpha in (0,1) required')
    ordered = np.sort(values)
    var = ordered[int(np.ceil(alpha * len(ordered))) - 1]
    # Integrate the empirical inverse CDF over [alpha, 1], including fractional boundary mass.
    tail_mass = (1 - alpha) * len(ordered)
    whole = int(np.floor(tail_mass))
    fraction = tail_mass - whole
    tail_total = ordered[len(ordered)-whole:].sum() if whole else 0.
    if fraction > 0:
        tail_total += fraction * ordered[len(ordered)-whole-1]
    return float(var), float(tail_total / tail_mass)


def summarize_losses(losses: np.ndarray, banks: list[str], alphas: list[float], seed: int) -> pd.DataFrame:
    if losses.ndim != 2 or losses.shape[1] != len(banks) or not np.isfinite(losses).all():
        raise ValueError('loss array shape or finiteness invalid')
    matrix = np.column_stack([losses, losses.sum(axis=1)])
    rows = []
    # MC uncertainty conditional on the fitted simulator, not parameter uncertainty.
    rng = np.random.default_rng(seed)
    # Independent simulation batches give an economical MC SE; full-sample
    # bootstrap quantile uncertainty is reported for portfolio tails below.
    for j, bank in enumerate([*banks, 'PORTFOLIO']):
        values = matrix[:, j]
        for alpha in alphas:
            var, es = empirical_tail(values, alpha)
            row = {'bank_id': bank, 'alpha': alpha, 'paths': len(values), 'mean': float(values.mean()),
                   'median': float(np.median(values)), 'var': var, 'es': es,
                   'mean_mc_se': float(values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 else 0.,
                   'var_mc_se': np.nan, 'es_mc_se': np.nan,
                   'half_sample_var': empirical_tail(values[:max(1, len(values)//2)], alpha)[0],
                   'half_sample_es': empirical_tail(values[:max(1, len(values)//2)], alpha)[1]}
            if bank == 'PORTFOLIO' and len(values) >= 100:
                samples = [empirical_tail(values[rng.integers(0, len(values), len(values))], alpha) for _ in range(100)]
                row['var_mc_se'], row['es_mc_se'] = np.std(samples, axis=0, ddof=1).tolist()
            rows.append(row)
    return pd.DataFrame(rows)
