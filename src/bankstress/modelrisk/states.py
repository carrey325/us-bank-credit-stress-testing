"""Portable fitted linear states; no implicit feature or bank fallback."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .bundle import write_json


@dataclass
class LinearState:
    predictors: list[str]
    coefficients: list[float]
    intercepts: dict[str, float]
    segment: str
    provenance: str

    def predict(self, data: pd.DataFrame) -> np.ndarray:
        banks = data.bank_id.astype(str)
        if not banks.isin(self.intercepts).all():
            raise ValueError('unknown bank in frozen model')
        if 'segment' in data and not data.segment.eq(self.segment).all():
            raise ValueError('frozen model segment mismatch')
        x = data[self.predictors].to_numpy(float)
        if not np.isfinite(x).all():
            raise ValueError('nonfinite frozen model features')
        return banks.map(self.intercepts).to_numpy(float) + x @ np.asarray(self.coefficients)

    def save(self, path: Path) -> None:
        write_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> 'LinearState':
        return cls(**json.loads(path.read_text(encoding='utf-8')))


def from_fe(fit: dict, segment: str) -> LinearState:
    means = fit['entity_means']
    intercept = means.nco_rate - means[fit['predictors']].to_numpy() @ fit['beta']
    return LinearState(list(fit['predictors']), fit['beta'].tolist(),
                       {entity.split('::')[0]: float(value) for entity, value in intercept.items()},
                       segment, 'RECONSTRUCTED')


def from_quantile(fit, segment: str) -> LinearState:
    coefficients = np.asarray(fit.result.params)
    intercepts = {fit.reference_bank: float(coefficients[0])}
    offset = 1 + len(fit.predictors)
    for bank in fit.bank_levels:
        if bank != fit.reference_bank:
            intercepts[bank] = float(coefficients[0] + coefficients[offset])
            offset += 1
    return LinearState(list(fit.predictors), coefficients[1:1 + len(fit.predictors)].tolist(),
                       intercepts, segment, 'RECONSTRUCTED')


def assert_training_cutoff(data: pd.DataFrame, cutoff: str | pd.Timestamp) -> None:
    if data.empty or data.target_period.isna().any() or (pd.to_datetime(data.target_period) > pd.Timestamp(cutoff)).any():
        raise ValueError('empty training data or training cutoff violation')
