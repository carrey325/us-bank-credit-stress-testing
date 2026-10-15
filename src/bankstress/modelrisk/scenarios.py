"""Stable VAR deviations and joint contiguous-block residual sampling."""
from __future__ import annotations

import numpy as np
import pandas as pd

MACROS = ['gdp_growth', 'unemployment_rate', 'bbb_spread', 'short_rate']


def contiguous_blocks(frame: pd.DataFrame, length: int = 4) -> np.ndarray:
    if length < 1 or frame.index.has_duplicates:
        raise ValueError('invalid block length or duplicate quarters')
    frame = frame.sort_index()
    periods = pd.DatetimeIndex(frame.index).to_period('Q').astype(int).to_numpy()
    values = frame.to_numpy(float)
    blocks = [values[i:i+length] for i in range(len(frame)-length+1)
              if np.isfinite(values[i:i+length]).all() and np.all(np.diff(periods[i:i+length]) == 1)]
    if not blocks:
        raise ValueError('no complete contiguous residual blocks')
    return np.stack(blocks)


def sample_blocks(blocks: np.ndarray, paths: int, horizon: int, rng: np.random.Generator) -> np.ndarray:
    if paths < 1 or horizon < 1:
        raise ValueError('positive path count and horizon required')
    count = int(np.ceil(horizon / blocks.shape[1]))
    indices = rng.integers(0, len(blocks), size=(paths, count))
    return blocks[indices].reshape(paths, count * blocks.shape[1], blocks.shape[2])[:, :horizon]


def fit_var(history: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    history = history.sort_index()
    if history.index.has_duplicates or history.isna().any().any() or not np.isfinite(history.to_numpy()).all():
        raise ValueError('macro history must be unique, complete and finite')
    periods = pd.DatetimeIndex(history.index).to_period('Q').astype(int)
    if not np.all(np.diff(periods) == 1) or len(history) < 20:
        raise ValueError('macro history requires at least 20 contiguous quarters')
    mean, scale = history.mean().to_numpy(), history.std(ddof=0).to_numpy()
    if np.any(scale <= 0):
        raise ValueError('constant macro feature')
    z = (history.to_numpy() - mean) / scale
    design = np.column_stack([np.ones(len(z)-1), z[:-1]])
    beta, _, rank, _ = np.linalg.lstsq(design, z[1:], rcond=None)
    if rank != design.shape[1]:
        raise ValueError('macro VAR design rank deficient')
    transition = beta[1:].T
    radius = float(max(abs(np.linalg.eigvals(transition))))
    if radius >= 1:
        raise ValueError(f'unstable macro VAR: spectral radius {radius}')
    residual = z[1:] - design @ beta
    residual -= residual.mean(axis=0)
    fitted = {'transition': transition.tolist(), 'intercept': beta[0].tolist(),
              'mean': mean.tolist(), 'scale': scale.tolist(), 'spectral_radius': radius,
              'columns': list(history.columns), 'calibration_start': str(history.index.min().date()),
              'calibration_end': str(history.index.max().date()),
              'innovation_covariance': np.cov(residual, rowvar=False).tolist()}
    return fitted, pd.DataFrame(residual, index=history.index[1:], columns=history.columns)


def fit_credit_factor(residuals: pd.DataFrame, minimum_fraction: float = .5,
                      minimum_quarters: int = 20) -> tuple[dict, pd.Series, pd.DataFrame, dict]:
    if residuals.index.has_duplicates or residuals.columns.has_duplicates:
        raise ValueError('duplicate credit residual keys')
    if not 0 < minimum_fraction <= 1 or minimum_quarters < 4:
        raise ValueError('invalid residual support thresholds')
    counts = residuals.notna().sum()
    scale = residuals.std(ddof=1)
    if (counts < minimum_quarters).any() or (scale <= 0).any() or scale.isna().any():
        raise ValueError('insufficient bank residual support or zero variance')
    centers = residuals.mean()
    z = (residuals - centers) / scale
    coverage = z.notna().mean(axis=1)
    factor = z.mean(axis=1).where(coverage >= minimum_fraction)
    factor -= factor.mean()
    loadings, idio = [], pd.DataFrame(index=z.index, columns=z.columns, dtype=float)
    for bank in z:
        paired = pd.concat([z[bank], factor.rename('factor')], axis=1).dropna()
        if len(paired) < minimum_quarters or paired.factor.var() <= 0:
            raise ValueError(f'insufficient common factor support: {bank}')
        loading = float(paired.iloc[:, 0].cov(paired.factor) / paired.factor.var())
        loadings.append(loading)
        remainder = z[bank] - loading * factor
        idio[bank] = remainder - remainder.mean()
    correlation = idio.corr(min_periods=minimum_quarters).to_numpy()
    off_diagonal = correlation[~np.eye(len(correlation), dtype=bool)]
    finite = off_diagonal[np.isfinite(off_diagonal)]
    support = {'bank_observations': {str(k): int(v) for k, v in counts.items()},
               'factor_quarters': int(factor.notna().sum()), 'factor_total_quarters': len(factor),
               'minimum_observed_bank_fraction': float(coverage.min()),
               'remaining_mean_absolute_pairwise_correlation': float(abs(finite).mean()) if len(finite) else None,
               'remaining_max_absolute_pairwise_correlation': float(abs(finite).max()) if len(finite) else None}
    fit = {'banks': [str(x) for x in z.columns], 'scale': scale.tolist(), 'loadings': loadings,
           'historical_residual_centers_removed': centers.tolist(),
           'assumption': 'Bank-specific blocks independent conditional on sampled common factor'}
    return fit, factor.rename('credit_factor'), idio, support


def draw_innovations(var: dict, innovations: pd.DataFrame, factor_fit: dict,
                     factor: pd.Series, idio: pd.DataFrame, paths: int, horizon: int,
                     seed: int, block_length: int = 4) -> tuple[np.ndarray, np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    joint = innovations.join(factor, how='inner').dropna()
    blocks = contiguous_blocks(joint, block_length)
    # Endpoint multiplicity and incomplete-quarter selection can shift the
    # bootstrap population mean. Recenter that population, not sampled paths.
    blocks = blocks - blocks.mean(axis=(0, 1))
    draw = sample_blocks(blocks, paths, horizon, rng)
    transition, scale = np.asarray(var['transition']), np.asarray(var['scale'])
    state = np.zeros((paths, len(scale)))
    deviations = np.empty((paths, horizon, len(scale)))
    for quarter in range(horizon):
        state = state @ transition.T + draw[:, quarter, :len(scale)]
        deviations[:, quarter] = state * scale
    credit = np.empty((paths, horizon, len(factor_fit['banks'])))
    block_counts = {}
    for j, bank in enumerate(factor_fit['banks']):
        specific_blocks = contiguous_blocks(idio[[bank]], block_length)
        specific_blocks = specific_blocks - specific_blocks.mean(axis=(0, 1))
        block_counts[bank] = len(specific_blocks)
        specific = sample_blocks(specific_blocks, paths, horizon, rng)[:, :, 0]
        credit[:, :, j] = (draw[:, :, -1] * factor_fit['loadings'][j] + specific) * factor_fit['scale'][j]
    diagnostics = {'joint_block_count': len(blocks), 'bank_block_counts': block_counts,
                   'joint_complete_quarters': len(joint), 'seed': seed, 'paths': paths,
                   'block_length': block_length, 'joint_innovation_correlation': joint.corr().to_numpy().tolist()}
    return deviations, credit, diagnostics
