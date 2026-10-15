"""Independent scores: deliberately imports neither estimators nor legacy metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

KEYS = ['bank_id', 'segment', 'forecast_origin', 'target_period']
IDENTITY = [*KEYS, 'window', 'model', 'tau', 'version']


def validate_forecasts(data: pd.DataFrame) -> None:
    required = {*IDENTITY, 'actual', 'prediction'}
    if not required.issubset(data):
        raise ValueError(f'missing forecast fields: {sorted(required - set(data))}')
    if data.empty or data[[*KEYS, 'window', 'model', 'version']].isna().any().any():
        raise ValueError('empty forecasts or missing keys')
    if data.duplicated(IDENTITY).any():
        raise ValueError('duplicate forecast keys')
    if not np.isfinite(data.prediction).all() or np.isinf(data.actual).any():
        raise ValueError('forecasts and observed actuals must be finite')
    if (data.tau.notna() & ~data.tau.between(0, 1, inclusive='neither')).any():
        raise ValueError('invalid quantile')
    if data.groupby(KEYS, dropna=False).actual.nunique(dropna=False).gt(1).any():
        raise ValueError('conflicting actual values or missingness')
    if (pd.to_datetime(data.forecast_origin) > pd.to_datetime(data.target_period)).any():
        raise ValueError('forecast origin after target')


def _score(group: pd.DataFrame, tau: float) -> dict:
    error = (group.actual - group.prediction).to_numpy(float)
    result = {'n': len(group), 'rmse': np.nan, 'mae': np.nan, 'bias': np.nan,
              'pinball_loss': np.nan, 'exceedance_rate': np.nan,
              'nominal_exceedance_rate': np.nan}
    if not len(error):
        return result
    if pd.isna(tau):
        result.update(rmse=float(np.sqrt(np.mean(error ** 2))), mae=float(np.mean(abs(error))),
                      bias=float(error.mean()))
    else:
        result.update(pinball_loss=float(np.mean(np.maximum(tau * error, (tau - 1) * error))),
                      exceedance_rate=float(np.mean(error > 0)), nominal_exceedance_rate=1 - tau)
    return result


def score_forecasts(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    validate_forecasts(data)
    retained, coverage = [], []
    # Model comparisons share the intersection within each estimand/version/window.
    for group_id, group in data.groupby(['window', 'segment', 'tau', 'version'], dropna=False, sort=True):
        models = list(group.groupby('model', sort=True))
        common = set.intersection(*(set(map(tuple, frame.loc[frame.actual.notna(), KEYS].to_numpy()))
                                    for _, frame in models))
        for model, frame in models:
            keep = pd.Series([tuple(row) in common for row in frame[KEYS].to_numpy()], index=frame.index)
            retained.append(frame.loc[keep])
            coverage.append(dict(zip(['window', 'segment', 'tau', 'version'], group_id)) |
                            {'model': model, 'generated_n': len(frame), 'missing_actual_n': int(frame.actual.isna().sum()),
                             'common_n': int(keep.sum()),
                             'common_key_excluded_n': int(frame.actual.notna().sum() - keep.sum())})
    aligned = pd.concat(retained, ignore_index=True)
    rows = []
    # Pool individual observations, never average window statistics.
    expanded = pd.concat([aligned, aligned.assign(window=0)], ignore_index=True)
    for key, frame in expanded.groupby(['window', 'segment', 'model', 'tau', 'version'], dropna=False):
        row = dict(zip(['window', 'segment', 'model', 'tau', 'version'], key)) | _score(frame, key[3])
        row.update(band_coverage=np.nan, nominal_band_coverage=np.nan, band_n=0)
        if key[3] == .9:
            low = expanded[(expanded.window == key[0]) & (expanded.segment == key[1]) &
                           (expanded.model == key[2]) & (expanded.version == key[4]) & (expanded.tau == .5)]
            paired = frame.merge(low[KEYS + ['prediction']], on=KEYS, suffixes=('', '_lower'), validate='one_to_one')
            if len(paired):
                row['band_coverage'] = float(paired.actual.between(paired.prediction_lower, paired.prediction).mean())
                row['nominal_band_coverage'] = .4
                row['band_n'] = len(paired)
        rows.append(row)
    # Keep empty comparisons visible rather than making unsupported models disappear.
    empty_source = pd.concat([data, data.assign(window=0)], ignore_index=True)
    populated = {(r['window'], r['segment'], r['model'], -1 if pd.isna(r['tau']) else r['tau'], r['version']) for r in rows}
    for key, frame in empty_source.groupby(['window', 'segment', 'model', 'tau', 'version'], dropna=False):
        marker = (key[0], key[1], key[2], -1 if pd.isna(key[3]) else key[3], key[4])
        if marker not in populated:
            rows.append(dict(zip(['window', 'segment', 'model', 'tau', 'version'], key)) |
                        _score(frame.iloc[:0], key[3]) |
                        {'band_coverage': np.nan, 'nominal_band_coverage': np.nan, 'band_n': 0})
    return pd.DataFrame(rows), pd.DataFrame(coverage)


def normalize_historical(inputs) -> pd.DataFrame:
    pieces = []
    for name, model in [('ar_predictions.parquet', 'ar'), ('fe_predictions.parquet', 'dynamic_fe')]:
        frame = pd.read_parquet(inputs / name)
        frame['bank_id'] = frame.bank_id.astype(str)
        pieces.append(frame.assign(model=model, tau=np.nan, version='ORIGINAL', actual=frame.nco_rate)[
            [*IDENTITY, 'actual', 'prediction']])
    frame = pd.read_parquet(inputs / 'quantile_predictions.parquet')
    frame['bank_id'] = frame.bank_id.astype(str)
    pieces.append(frame.assign(model=frame.model_family, version=frame.prediction_version, actual=frame.nco_rate)[
        [*IDENTITY, 'actual', 'prediction']])
    result = pd.concat(pieces, ignore_index=True)
    validate_forecasts(result)
    return result
