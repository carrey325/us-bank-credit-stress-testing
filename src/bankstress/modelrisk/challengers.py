"""Small predeclared challenger grids, selected using training quarters only."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def temporal_splits(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    periods = np.sort(frame.target_period.unique())
    if len(periods) < 12:
        raise ValueError('at least 12 training quarters needed for temporal selection')
    cuts = np.linspace(len(periods) // 2, len(periods), 4, dtype=int)
    splits = []
    for start, end in zip(cuts[:-1], cuts[1:]):
        train = np.flatnonzero(frame.target_period.isin(periods[:start]))
        valid = np.flatnonzero(frame.target_period.isin(periods[start:end]))
        splits.append((train, valid))
    return splits


@dataclass
class ChallengerState:
    pipeline: Pipeline
    predictors: list[str]
    banks: list[str]

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if not frame.bank_id.astype(str).isin(self.banks).all():
            raise ValueError('unknown bank in challenger')
        if not np.isfinite(frame[self.predictors].to_numpy(float)).all():
            raise ValueError('nonfinite challenger features')
        return self.pipeline.predict(frame.assign(bank_id=frame.bank_id.astype(str)))

    def save(self, path: Path) -> None:
        joblib.dump(self, path)


def load_challenger(path: Path) -> ChallengerState:
    """Load only trusted locally generated artifacts after bundle verification."""
    return joblib.load(path)


def _pipeline(predictors: list[str], family: str, candidate: float | int, tau: float | None, seed: int) -> Pipeline:
    transform = ColumnTransformer([
        ('numeric', StandardScaler(), predictors),
        ('bank', OneHotEncoder(handle_unknown='error', sparse_output=False), ['bank_id']),
    ], sparse_threshold=0)
    if family == 'ridge':
        if tau is not None:
            raise ValueError('Ridge is a mean challenger only')
        estimator = Ridge(alpha=float(candidate))
    elif family == 'gradient_boosting':
        estimator = GradientBoostingRegressor(
            loss='squared_error' if tau is None else 'quantile', alpha=.9 if tau is None else tau,
            n_estimators=100, max_depth=int(candidate), min_samples_leaf=10,
            learning_rate=.05, random_state=seed)
    else:
        raise ValueError(f'unsupported challenger {family}')
    return Pipeline([('features', transform), ('estimator', estimator)])


def fit_challenger(frame: pd.DataFrame, predictors: list[str], family: str,
                   tau: float | None, seed: int) -> tuple[ChallengerState, list[dict]]:
    frame = frame.sort_values(['target_period', 'bank_id']).reset_index(drop=True).copy()
    frame['bank_id'] = frame.bank_id.astype(str)
    candidates = [0.1, 1., 10.] if family == 'ridge' else [1, 2]
    splits = temporal_splits(frame)
    audit, totals = [], []
    for candidate in candidates:
        total, count = 0., 0
        for fold, (training, validation) in enumerate(splits, 1):
            train, valid = frame.iloc[training], frame.iloc[validation]
            original_n = len(valid)
            valid = valid[valid.bank_id.isin(train.bank_id)]
            if valid.empty:
                raise ValueError('no known-bank inner validation observations')
            pipe = _pipeline(predictors, family, candidate, tau, seed)
            pipe.fit(train, train.nco_rate)
            error = valid.nco_rate.to_numpy() - pipe.predict(valid)
            losses = error ** 2 if tau is None else np.maximum(tau * error, (tau - 1) * error)
            total += float(losses.sum())
            count += len(valid)
            audit.append({'candidate': candidate, 'fold': fold, 'loss': float(losses.mean()),
                          'train_end': str(train.target_period.max().date()),
                          'validation_start': str(valid.target_period.min().date()),
                          'validation_end': str(valid.target_period.max().date()),
                          'train_n': len(train), 'validation_n': len(valid),
                          'unknown_bank_exclusions': original_n - len(valid)})
        totals.append((total / count, candidate))
    selected = min(totals)[1]
    pipe = _pipeline(predictors, family, selected, tau, seed)
    pipe.fit(frame, frame.nco_rate)
    for row in audit:
        row['selected'] = row['candidate'] == selected
    return ChallengerState(pipe, predictors, sorted(frame.bank_id.unique())), audit
