"""Batch 3 tail-model, Bayesian, and historical-validation routines.

The module deliberately keeps forecasts conditional on the same Batch 2
features.  Historical pseudo-stress uses realised macro paths only; future bank
controls are frozen at their last pre-window value, so no future bank outcome or
control is leaked into a recursive forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from matplotlib import pyplot as plt
from statsmodels.regression.quantile_regression import QuantReg

from bankstress.modeling import _eligible_frame, _fit_entity_fe, _metrics, _predict_entity_fe, load_model_specs


def _directories(root: Path) -> tuple[Path, Path]:
    models = root / "outputs" / "models"
    validation = root / "outputs" / "validation"
    (models / "quantile").mkdir(parents=True, exist_ok=True)
    (models / "bayesian").mkdir(parents=True, exist_ok=True)
    validation.mkdir(parents=True, exist_ok=True)
    return models, validation


def pinball_loss(actual: pd.Series | np.ndarray, forecast: pd.Series | np.ndarray, quantile: float) -> float:
    error = np.asarray(actual, dtype=float) - np.asarray(forecast, dtype=float)
    return float(np.maximum(quantile * error, (quantile - 1) * error).mean())


def interval_scores(
    actual: pd.Series | np.ndarray,
    lower: pd.Series | np.ndarray,
    upper: pd.Series | np.ndarray,
    *,
    lower_quantile: float,
    upper_quantile: float,
) -> dict[str, float]:
    """Score a quantile interval with the proper penalty for each bound.

    For an equal-tailed interval this is the ordinary Winkler score.  For an
    asymmetric band, each miss is instead weighted by its own tail probability:
    ``1 / lower_quantile`` below the lower bound and
    ``1 / (1 - upper_quantile)`` above the upper bound.  This matters for the
    retained Q0.50--Q0.90 band, whose two tails are deliberately unequal.
    """
    actual_array, lower_array, upper_array = (np.asarray(item, dtype=float) for item in (actual, lower, upper))
    if np.any(upper_array < lower_array):
        raise ValueError("Prediction interval upper bound is below lower bound")
    if not 0 < lower_quantile < upper_quantile < 1:
        raise ValueError("Interval quantiles must satisfy 0 < lower < upper < 1")
    width = upper_array - lower_array
    penalty = np.where(actual_array < lower_array, (lower_array - actual_array) / lower_quantile, 0)
    penalty += np.where(actual_array > upper_array, (actual_array - upper_array) / (1 - upper_quantile), 0)
    return {
        "empirical_coverage": float(((actual_array >= lower_array) & (actual_array <= upper_array)).mean()),
        "interval_width": float(width.mean()),
        "winkler_score": float((width + penalty).mean()),
        "nominal_coverage": upper_quantile - lower_quantile,
    }


def _crisis_period_mask(dates: pd.Series) -> pd.Series:
    """Return the pre-specified historical pseudo-stress periods.

    This intentionally uses the same three periods as the historical validation
    rather than selecting periods after inspecting forecast errors.
    """
    values = pd.to_datetime(dates)
    return (
        values.between(pd.Timestamp("2007-01-01"), pd.Timestamp("2010-12-31"))
        | values.between(pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"))
        | values.between(pd.Timestamp("2022-01-01"), pd.Timestamp("2025-12-31"))
    )


@dataclass
class QuantileFit:
    result: Any
    predictors: list[str]
    bank_levels: list[str]
    reference_bank: str
    quantile: float


def _quantile_design(data: pd.DataFrame, predictors: list[str], bank_levels: list[str], reference_bank: str) -> pd.DataFrame:
    features = data[predictors].astype(float).copy()
    bank = data["bank_id"].astype(str)
    for level in bank_levels:
        if level != reference_bank:
            features[f"bank::{level}"] = (bank == level).astype(float)
    features.insert(0, "const", 1.0)
    return features


def fit_quantile(train: pd.DataFrame, predictors: list[str], quantile: float, spec: dict) -> QuantileFit:
    frame = train.dropna(subset=["nco_rate", *predictors]).copy()
    bank_levels = sorted(frame["bank_id"].astype(str).unique())
    if len(bank_levels) < 2:
        raise ValueError("Quantile model requires at least two banks for bank-segment effects")
    reference_bank = bank_levels[0]
    design = _quantile_design(frame, predictors, bank_levels, reference_bank)
    result = QuantReg(frame["nco_rate"].to_numpy(float), design.to_numpy(float)).fit(
        q=quantile, max_iter=int(spec["max_iter"]), p_tol=float(spec["p_tol"])
    )
    return QuantileFit(result, predictors, bank_levels, reference_bank, quantile)


def predict_quantile(fit: QuantileFit, data: pd.DataFrame) -> pd.DataFrame:
    frame = data.dropna(subset=["nco_rate", *fit.predictors]).copy()
    frame = frame[frame["bank_id"].astype(str).isin(fit.bank_levels)].copy()
    design = _quantile_design(frame, fit.predictors, fit.bank_levels, fit.reference_bank)
    frame["prediction"] = fit.result.predict(design.to_numpy(float))
    return frame


def _spj_fit(train: pd.DataFrame, predictors: list[str]) -> dict:
    dates = sorted(pd.to_datetime(train["report_date"]).unique())
    if len(dates) < 4:
        raise ValueError("Split-panel jackknife needs at least four training quarters")
    midpoint = dates[len(dates) // 2 - 1]
    full = _fit_entity_fe(train, "nco_rate", predictors)
    first = _fit_entity_fe(train[train["report_date"] <= midpoint], "nco_rate", predictors)
    second = _fit_entity_fe(train[train["report_date"] > midpoint], "nco_rate", predictors)
    corrected = dict(full)
    corrected["beta"] = 2 * full["beta"] - (first["beta"] + second["beta"]) / 2
    return corrected


def _bayesian_available() -> tuple[Any | None, Any | None]:
    try:
        import arviz as az
        import pymc as pm
    except ImportError:
        return None, None
    return pm, az


@dataclass
class BayesianFit:
    posterior: Any
    segment_levels: list[str]
    entity_levels: list[str]
    predictor_names: list[str]
    feature_scaling: dict[str, tuple[float, float]]
    outcome_scale: float
    diagnostics: dict[str, Any]


def _bayesian_matrix(data: pd.DataFrame, predictors_by_segment: dict[str, list[str]], scaling: dict[str, tuple[float, float]] | None = None) -> tuple[np.ndarray, list[str], dict[str, tuple[float, float]]]:
    names = [f"{segment}::{term}" for segment, terms in predictors_by_segment.items() for term in terms]
    matrix = np.zeros((len(data), len(names)))
    scales = {} if scaling is None else scaling
    for segment, terms in predictors_by_segment.items():
        mask = data["segment"].eq(segment).to_numpy()
        for term in terms:
            name = f"{segment}::{term}"
            if scaling is None:
                mean = float(data.loc[mask, term].mean())
                sd = float(data.loc[mask, term].std(ddof=0))
                scales[name] = (mean, sd if sd > 1e-12 else 1.0)
            mean, sd = scales[name]
            matrix[mask, names.index(name)] = (data.loc[mask, term].to_numpy(float) - mean) / sd
    return matrix, names, scales


def fit_bayesian(train: pd.DataFrame, predictors_by_segment: dict[str, list[str]], spec: dict) -> BayesianFit:
    pm, az = _bayesian_available()
    if pm is None or az is None:
        raise RuntimeError("PyMC and ArviZ are required; install the project's bayesian extra")
    frame = train.copy()
    segments = list(predictors_by_segment)
    frame = frame[frame["segment"].isin(segments)].copy()
    required = ["nco_rate", *[term for terms in predictors_by_segment.values() for term in terms]]
    frame = frame.dropna(subset=required).copy()
    frame["entity"] = frame["bank_id"].astype(str) + "::" + frame["segment"]
    segment_levels = segments
    entity_levels = sorted(frame["entity"].unique())
    segment_index = pd.Categorical(frame["segment"], categories=segment_levels).codes
    entity_index = pd.Categorical(frame["entity"], categories=entity_levels).codes
    x, predictor_names, scaling = _bayesian_matrix(frame, predictors_by_segment)
    outcome_scale = float(frame["nco_rate"].std(ddof=0))
    if not np.isfinite(outcome_scale) or outcome_scale <= 1e-12:
        raise ValueError("Bayesian outcome lacks variation")
    y = frame["nco_rate"].to_numpy(float) / outcome_scale
    prior = spec["priors"]
    coords = {"segment": segment_levels, "entity": entity_levels, "predictor": predictor_names}
    with pm.Model(coords=coords) as model:
        alpha = pm.Normal("alpha", 0, float(prior["standardized_intercept_sd"]), dims="segment")
        entity_sd = pm.HalfNormal("entity_sd", float(prior["standardized_entity_sd"]))
        entity_raw = pm.Normal("entity_raw", 0, 1, dims="entity")
        beta = pm.Normal("beta", 0, float(prior["standardized_coefficient_sd"]), dims="predictor")
        sigma = pm.HalfNormal("sigma", float(prior["standardized_residual_sd"]), dims="segment")
        nu = pm.Exponential("nu_minus_two", float(prior["student_t_nu_minus_two_rate"])) + 2
        mu = alpha[segment_index] + entity_raw[entity_index] * entity_sd + pm.math.dot(x, beta)
        pm.StudentT("nco", nu=nu, mu=mu, sigma=sigma[segment_index], observed=y)
        posterior = pm.sample(draws=int(spec["draws"]), tune=int(spec["tune"]), chains=int(spec["chains"]), cores=1,
                              random_seed=int(spec["random_seed"]), target_accept=float(spec["target_accept"]),
                              progressbar=False, compute_convergence_checks=False)
    summary = az.summary(posterior, var_names=["alpha", "entity_sd", "beta", "sigma", "nu_minus_two"], round_to=None)
    divergences = int(posterior.sample_stats["diverging"].sum().item())
    stacked = posterior.posterior.stack(sample=("chain", "draw"))
    alpha_draws = stacked["alpha"].values
    entity_draws = stacked["entity_raw"].values * stacked["entity_sd"].values
    beta_draws = stacked["beta"].values
    sigma_draws = stacked["sigma"].values
    nu_draws = stacked["nu_minus_two"].values + 2
    mu_draws = alpha_draws[segment_index, :] + entity_draws[entity_index, :] + x @ beta_draws
    rng = np.random.default_rng(int(spec["random_seed"]))
    replicated = (mu_draws + rng.standard_t(nu_draws, size=mu_draws.shape) * sigma_draws[segment_index, :]) * outcome_scale
    observed = frame["nco_rate"].to_numpy(float)
    diagnostics = {
        "status": "sampled",
        "rhat_max": float(summary["r_hat"].max()),
        "ess_bulk_min": float(summary["ess_bulk"].min()),
        "divergences": divergences,
        "nobs": len(frame),
        "entities": len(entity_levels),
        "ppc_mean_error": float(replicated.mean() - observed.mean()),
        "ppc_q90_error": float(np.quantile(replicated, 0.9) - np.quantile(observed, 0.9)),
    }
    return BayesianFit(posterior, segment_levels, entity_levels, predictor_names, scaling, outcome_scale, diagnostics)


def predict_bayesian(fit: BayesianFit, data: pd.DataFrame, predictors_by_segment: dict[str, list[str]], seed: int = 772) -> pd.DataFrame:
    frame = data.copy()
    frame["entity"] = frame["bank_id"].astype(str) + "::" + frame["segment"]
    frame = frame[frame["entity"].isin(fit.entity_levels) & frame["segment"].isin(fit.segment_levels)].copy()
    x, names, _ = _bayesian_matrix(frame, predictors_by_segment, fit.feature_scaling)
    if names != fit.predictor_names:
        raise ValueError("Bayesian predictor order changed between fit and prediction")
    posterior = fit.posterior.posterior.stack(sample=("chain", "draw"))
    alpha = posterior["alpha"].values
    entity_effect = posterior["entity_raw"].values * posterior["entity_sd"].values
    beta = posterior["beta"].values
    sigma = posterior["sigma"].values
    nu = posterior["nu_minus_two"].values + 2
    segment_idx = pd.Categorical(frame["segment"], categories=fit.segment_levels).codes
    entity_idx = pd.Categorical(frame["entity"], categories=fit.entity_levels).codes
    mu = alpha[segment_idx, :] + entity_effect[entity_idx, :] + x @ beta
    rng = np.random.default_rng(seed)
    draws = mu + rng.standard_t(nu, size=mu.shape) * sigma[segment_idx, :]
    draws *= fit.outcome_scale
    frame["prediction"] = draws.mean(axis=1)
    frame["posterior_lower"] = np.quantile(draws, 0.05, axis=1)
    frame["posterior_upper"] = np.quantile(draws, 0.95, axis=1)
    frame["posterior_median"] = np.quantile(draws, 0.5, axis=1)
    return frame


def _bayesian_convergence_failure(diagnostics: dict[str, Any], convergence: dict[str, Any]) -> str | None:
    """Return an explicit exclusion reason when posterior diagnostics fail."""
    failures = []
    if not np.isfinite(diagnostics["rhat_max"]) or diagnostics["rhat_max"] >= float(convergence["rhat_max"]):
        failures.append(f"R-hat max {diagnostics['rhat_max']:.4f} is not below {float(convergence['rhat_max']):.2f}")
    if diagnostics["ess_bulk_min"] < float(convergence["ess_bulk_min"]):
        failures.append(f"bulk ESS minimum {diagnostics['ess_bulk_min']:.1f} is below {float(convergence['ess_bulk_min']):.0f}")
    if diagnostics["divergences"] != int(convergence["divergences_ideal"]):
        failures.append(f"divergences {diagnostics['divergences']} differs from ideal {int(convergence['divergences_ideal'])}")
    return "; ".join(failures) if failures else None


def _predictors_by_segment(sample: pd.DataFrame, spec: dict) -> dict[str, list[str]]:
    output = {}
    for segment in spec["primary_segments"]:
        subset = sample[sample["segment"].eq(segment)]
        if subset.empty:
            continue
        output[segment] = subset["sample_predictors"].iloc[0].split("|")
    return output


def _mean_rows(predictions: pd.DataFrame, window_id: int, segment: str, model: str, window: dict) -> tuple[pd.DataFrame, dict]:
    result = predictions[["bank_id", "segment", "report_date", "nco_rate", "prediction"]].copy()
    result["window"] = window_id
    result["model"] = model
    result["forecast_type"] = "mean"
    metric = {"window": window_id, "segment": segment, "model": model, "metric_family": "mean", **window, **_metrics(predictions)}
    return result, metric


def run_unified_oos(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run all Batch 3 estimators on Batch 2's frozen expanding windows."""
    spec = load_model_specs(root)
    _, validation = _directories(root)
    eligible = _eligible_frame(panel, spec)
    predictors_by_segment = _predictors_by_segment(eligible, spec)
    prediction_rows: list[pd.DataFrame] = []
    comparison_rows: list[dict] = []
    tail_rows: list[dict] = []
    diagnostics: list[dict] = []
    interval = spec["quantile_spec"]["interval"]
    lower_q, upper_q = (float(interval[item]) for item in ("lower_quantile", "upper_quantile"))
    for window_id, window in enumerate(spec["oos_windows"], start=1):
        train = eligible[eligible["report_date"].between(pd.Timestamp(window["train_start"]), pd.Timestamp(window["train_end"]))].copy()
        test = eligible[eligible["report_date"].between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"]))].copy()
        for segment, predictors in predictors_by_segment.items():
            train_segment, test_segment = train[train.segment.eq(segment)], test[test.segment.eq(segment)]
            for model_name, fit in (("ar", _fit_entity_fe(train_segment, "nco_rate", ["lagged_nco_rate"])),
                                    ("dynamic_fe", _fit_entity_fe(train_segment, "nco_rate", predictors)),
                                    ("bias_corrected_fe", _spj_fit(train_segment, predictors))):
                predicted = _predict_entity_fe(fit, test_segment, "nco_rate")
                row, metric = _mean_rows(predicted, window_id, segment, model_name, window)
                prediction_rows.append(row)
                comparison_rows.append(metric)
            quantile_predictions: dict[float, pd.DataFrame] = {}
            for quantile in spec["quantiles"]:
                fit = fit_quantile(train_segment, predictors, float(quantile), spec["quantile_spec"])
                predicted = predict_quantile(fit, test_segment)
                predicted["quantile"] = float(quantile)
                quantile_predictions[float(quantile)] = predicted
            # Independently fitted conditional quantiles can cross in finite
            # samples.  Rearrangement is a deterministic monotonicity repair;
            # retain and report its count rather than silently treating a
            # crossing pair as an interval.
            keys = ["bank_id", "segment", "report_date"]
            common = set.intersection(*(set(map(tuple, frame[keys].to_numpy())) for frame in quantile_predictions.values()))
            ordered_keys = sorted(common)
            raw_matrix = np.column_stack([
                quantile_predictions[quantile].set_index(keys).loc[ordered_keys, "prediction"].to_numpy()
                for quantile in sorted(quantile_predictions)
            ])
            crossing_count = int(np.any(np.diff(raw_matrix, axis=1) < 0, axis=1).sum())
            repaired = np.sort(raw_matrix, axis=1)
            for column, quantile in enumerate(sorted(quantile_predictions)):
                repaired_frame = quantile_predictions[quantile].set_index(keys).loc[ordered_keys].copy()
                repaired_frame["prediction"] = repaired[:, column]
                quantile_predictions[quantile] = repaired_frame.reset_index()
                predicted = quantile_predictions[quantile]
                row = predicted[["bank_id", "segment", "report_date", "nco_rate", "prediction", "quantile"]].copy()
                row["window"], row["model"], row["forecast_type"] = window_id, f"quantile_{quantile}", "quantile"
                prediction_rows.append(row)
                tail_rows.append({"window": window_id, "segment": segment, "model": f"quantile_{quantile}", "metric": "pinball_loss",
                                  "value": pinball_loss(predicted.nco_rate, predicted.prediction, float(quantile)), "quantile": float(quantile), **window})
                tail_rows.append({"window": window_id, "segment": segment, "model": f"quantile_{quantile}", "metric": "severe_underprediction_count",
                                  "value": int((predicted.nco_rate > predicted.prediction).sum()) if float(quantile) == float(spec["quantile_spec"]["tail_threshold_quantile"]) else np.nan,
                                  "quantile": float(quantile), **window})
                tail_rows.append({"window": window_id, "segment": segment, "model": f"quantile_{quantile}", "metric": "crisis_underprediction_count",
                                  "value": int(((predicted.nco_rate > predicted.prediction) & _crisis_period_mask(predicted.report_date)).sum()) if float(quantile) == float(spec["quantile_spec"]["tail_threshold_quantile"]) else np.nan,
                                  "quantile": float(quantile), **window})
            tail_rows.append({"window": window_id, "segment": segment, "model": "quantile_rearrangement", "metric": "crossing_count",
                              "value": crossing_count, "quantile": np.nan, **window})
            low, high = quantile_predictions[lower_q], quantile_predictions[upper_q]
            aligned = low.merge(high[["bank_id", "segment", "report_date", "prediction"]], on=["bank_id", "segment", "report_date"], suffixes=("_lower", "_upper"), validate="one_to_one")
            for metric, value in interval_scores(
                aligned.nco_rate,
                aligned.prediction_lower,
                aligned.prediction_upper,
                lower_quantile=lower_q,
                upper_quantile=upper_q,
            ).items():
                tail_rows.append({"window": window_id, "segment": segment, "model": f"quantile_{lower_q}_{upper_q}_band", "metric": metric,
                                  "value": value, "quantile": np.nan, "lower_quantile": lower_q, "upper_quantile": upper_q, **window})
        if os.environ.get("BANKSTRESS_SKIP_BAYESIAN") == "1":
            diagnostics.append({"window": window_id, "status": "environment_fallback", "reason": "Bayesian sampling explicitly skipped by BANKSTRESS_SKIP_BAYESIAN=1; no posterior results are used."})
            continue
        try:
            fit = fit_bayesian(train, predictors_by_segment, spec["bayesian_core_spec"])
            convergence_failure = _bayesian_convergence_failure(fit.diagnostics, spec["bayesian_core_spec"]["convergence"])
            if convergence_failure:
                diagnostics.append({"window": window_id, **fit.diagnostics, "status": "nonconverged_fallback", "reason": convergence_failure})
                continue
            predicted = predict_bayesian(fit, test, predictors_by_segment, int(spec["bayesian_core_spec"]["random_seed"]) + window_id)
            for segment in predictors_by_segment:
                segment_predicted = predicted[predicted.segment.eq(segment)]
                row, metric = _mean_rows(segment_predicted, window_id, segment, "bayesian", window)
                row["posterior_lower"] = segment_predicted["posterior_lower"].to_numpy()
                row["posterior_upper"] = segment_predicted["posterior_upper"].to_numpy()
                prediction_rows.append(row)
                comparison_rows.append(metric)
                values = interval_scores(
                    segment_predicted.nco_rate,
                    segment_predicted.posterior_lower,
                    segment_predicted.posterior_upper,
                    lower_quantile=0.05,
                    upper_quantile=0.95,
                )
                for name, value in values.items():
                    tail_rows.append({"window": window_id, "segment": segment, "model": "bayesian_90pct_interval", "metric": name,
                                      "value": value, "quantile": np.nan, "lower_quantile": 0.05, "upper_quantile": 0.95, **window})
            diagnostics.append({"window": window_id, **fit.diagnostics})
        except Exception as error:  # optional dependency or a recorded convergence/fitting fallback
            diagnostics.append({"window": window_id, "status": "unavailable_or_failed", "reason": f"{type(error).__name__}: {error}"})
    predictions = pd.concat(prediction_rows, ignore_index=True)
    comparison = pd.DataFrame(comparison_rows)
    tail = pd.DataFrame(tail_rows)
    diagnostics_frame = pd.DataFrame(diagnostics)
    predictions.to_parquet(validation / "oos_predictions.parquet", index=False)
    comparison.to_csv(validation / "model_comparison.csv", index=False)
    tail.to_csv(validation / "tail_metrics.csv", index=False)
    diagnostics_frame.to_csv(root / "outputs" / "models" / "bayesian" / "diagnostics.csv", index=False)
    if diagnostics_frame["status"].ne("sampled").any():
        (root / "outputs" / "models" / "bayesian" / "result_status.md").write_text(
            "# Bayesian result status\n\nAt least one Bayesian OOS fit did not complete. Its posterior forecasts and intervals are intentionally excluded from model comparison; inspect `diagnostics.csv` for the recorded fallback reason.\n",
            encoding="utf-8",
        )
    (root / "outputs" / "models" / "quantile" / "specification.yaml").write_text(yaml.safe_dump(spec["quantile_spec"], sort_keys=False), encoding="utf-8")
    (root / "outputs" / "models" / "bayesian" / "specification.yaml").write_text(yaml.safe_dump(spec["bayesian_core_spec"], sort_keys=False), encoding="utf-8")
    return eligible, predictions, comparison, tail


def _freeze_future_bank_controls(train: pd.DataFrame, future: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    controls = [term for term in predictors if term not in {"lagged_nco_rate"} and not term.startswith("lagged_gdp_") and not term.startswith("lagged_unemployment_") and not term.startswith("lagged_cre_price_") and not term.startswith("lagged_bbb_") and not term.startswith("lagged_short_")]
    output = future.copy()
    latest = train.sort_values("report_date").groupby("bank_id")[controls].last()
    for control in controls:
        output[control] = output["bank_id"].map(latest[control])
    return output


def _recursive_predict(fit: Any, method: str, train: pd.DataFrame, future: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    prepared = _freeze_future_bank_controls(train, future, predictors)
    states = train.sort_values("report_date").groupby("bank_id")["nco_rate"].last().to_dict()
    pieces: list[pd.DataFrame] = []
    for date, period in prepared.sort_values("report_date").groupby("report_date", sort=True):
        current = period.copy()
        current["lagged_nco_rate"] = current["bank_id"].map(states)
        if method == "fe":
            predicted = _predict_entity_fe(fit, current, "nco_rate")
        else:
            predicted = predict_quantile(fit, current)
        states.update(dict(zip(predicted["bank_id"], predicted["prediction"], strict=True)))
        pieces.append(predicted)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def run_historical_pseudo_stress(panel: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Recursive GFC, COVID, and high-rate/CRE forecasts using realised macro paths."""
    spec = load_model_specs(root)
    _, validation = _directories(root)
    eligible = _eligible_frame(panel, spec)
    predictors_by_segment = _predictors_by_segment(eligible, spec)
    rows: list[pd.DataFrame] = []
    for window in spec["pseudo_stress_windows"]:
        train = eligible[eligible.report_date.le(pd.Timestamp(window["train_end"]))].copy()
        future = eligible[eligible.report_date.between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"]))].copy()
        for segment, predictors in predictors_by_segment.items():
            train_segment, future_segment = train[train.segment.eq(segment)], future[future.segment.eq(segment)]
            fits: list[tuple[str, Any, str]] = [
                ("ar", _fit_entity_fe(train_segment, "nco_rate", ["lagged_nco_rate"]), "fe"),
                ("dynamic_fe", _fit_entity_fe(train_segment, "nco_rate", predictors), "fe"),
                ("bias_corrected_fe", _spj_fit(train_segment, predictors), "fe"),
            ]
            fits.extend((f"quantile_{quantile}", fit_quantile(train_segment, predictors, float(quantile), spec["quantile_spec"]), "quantile") for quantile in spec["quantiles"])
            for model, fit, kind in fits:
                predicted = _recursive_predict(fit, kind, train_segment, future_segment, predictors if model != "ar" else ["lagged_nco_rate"])
                predicted["pseudo_window"], predicted["model"] = window["name"], model
                rows.append(predicted[["pseudo_window", "model", "bank_id", "segment", "report_date", "nco_rate", "prediction"]])
    result = pd.concat(rows, ignore_index=True)
    result.to_parquet(validation / "pseudo_stress.parquet", index=False)
    error = result["nco_rate"] - result["prediction"]
    result_with_error = result.assign(_absolute_error=error.abs(), _squared_error=error.pow(2), _error=error)
    summary_rows: list[dict[str, float | int | str]] = []
    for (pseudo_window, model, segment), group in result_with_error.groupby(["pseudo_window", "model", "segment"], sort=True):
        quantile = float(model.removeprefix("quantile_")) if model.startswith("quantile_") else np.nan
        is_quantile = np.isfinite(quantile)
        summary_rows.append({
            "pseudo_window": pseudo_window,
            "model": model,
            "segment": segment,
            "n": len(group),
            "rmse": float(np.sqrt(group["_squared_error"].mean())),
            "mae": float(group["_absolute_error"].mean()),
            "bias": float(group["_error"].mean()),
            "quantile": quantile,
            "pinball_loss": pinball_loss(group["nco_rate"], group["prediction"], quantile) if is_quantile else np.nan,
            "exceedance_count": int((group["nco_rate"] > group["prediction"]).sum()) if is_quantile else np.nan,
            "empirical_exceedance_rate": float((group["nco_rate"] > group["prediction"]).mean()) if is_quantile else np.nan,
            "nominal_exceedance_rate": 1 - quantile if is_quantile else np.nan,
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(validation / "pseudo_stress_metrics.csv", index=False)
    with (validation / "pseudo_stress_methodology.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump({
            "macro_path": "realised historical macro path",
            "lagged_nco": "recursive predicted NCO after jump-off",
            "bank_controls": "last pre-window value, held fixed",
            "windows": spec["pseudo_stress_windows"],
            "tail_model_limitation": (
                "Recursive CRE Q0.90 paths are unstable in the COVID and 2022+ high-rate/CRE windows; "
                "these historical paths are diagnostic tail-model evidence, not full recursive-stress validation."
            ),
        }, handle, sort_keys=False)
    return result


def write_validation_figures(predictions: pd.DataFrame, pseudo_stress: pd.DataFrame, root: Path) -> None:
    """Write the six Batch 3 figures from generated forecasts, never hard-coded values."""
    figure_dir = root / "outputs" / "validation" / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    def save_line(frame: pd.DataFrame, path: Path, title: str, series: dict[str, pd.Series]) -> None:
        fig, ax = plt.subplots(figsize=(10, 5))
        for label, values in series.items():
            ax.plot(values.index, values.values, label=label)
        ax.set_title(title)
        ax.set_xlabel("Quarter")
        ax.set_ylabel("NCO rate")
        ax.legend()
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)

    fe = predictions[predictions.model.eq("dynamic_fe")]
    if not fe.empty:
        save_line(fe, figure_dir / "fe_mean_vs_actual.png", "Dynamic FE OOS mean forecast", {
            "actual": fe.groupby("report_date")["nco_rate"].mean(), "Dynamic FE": fe.groupby("report_date")["prediction"].mean(),
        })
    quantile = predictions[predictions.model.isin(["quantile_0.75", "quantile_0.9"])]
    if not quantile.empty:
        bands = quantile.pivot_table(index="report_date", columns="model", values="prediction", aggfunc="mean")
        actual = quantile.groupby("report_date")["nco_rate"].mean()
        save_line(quantile, figure_dir / "quantile_75_90_bands.png", "OOS 75th and 90th quantile forecasts", {
            "actual": actual, "q75": bands["quantile_0.75"], "q90": bands["quantile_0.9"],
        })
    bayesian = predictions[predictions.model.eq("bayesian")]
    if not bayesian.empty:
        grouped = bayesian.groupby("report_date")
        mean = grouped["prediction"].mean()
        lower, upper = grouped["posterior_lower"].mean(), grouped["posterior_upper"].mean()
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(mean.index, grouped["nco_rate"].mean(), label="actual")
        ax.plot(mean.index, mean, label="posterior predictive mean")
        ax.fill_between(mean.index, lower, upper, alpha=0.25, label="90% posterior interval")
        ax.set(title="Bayesian OOS posterior predictive interval", xlabel="Quarter", ylabel="NCO rate")
        ax.legend()
        fig.tight_layout()
        fig.savefig(figure_dir / "bayesian_posterior_interval.png", dpi=150)
        plt.close(fig)
    else:
        # The approved fallback prohibits presenting an un-sampled posterior as
        # evidence.  Keep the mandatory figure slot reproducible, but make the
        # unavailable posterior explicit rather than drawing invented bands.
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.axis("off")
        ax.text(
            0.5,
            0.55,
            "Bayesian posterior predictive interval unavailable",
            ha="center",
            va="center",
            fontsize=15,
        )
        ax.text(
            0.5,
            0.42,
            "See outputs/models/bayesian/diagnostics.csv and result_status.md;\nno posterior forecast is shown under the documented fallback.",
            ha="center",
            va="center",
        )
        fig.tight_layout()
        fig.savefig(figure_dir / "bayesian_posterior_interval.png", dpi=150)
        plt.close(fig)
    for window, filename, title in (("GFC", "gfc_pseudo_stress.png", "GFC pseudo-stress"), ("COVID", "covid_pseudo_stress.png", "COVID pseudo-stress"), ("High_Rate_CRE", "high_rate_cre_pseudo_stress.png", "2022+ high-rate / CRE pseudo-stress")):
        frame = pseudo_stress[(pseudo_stress.pseudo_window.eq(window)) & (pseudo_stress.model.eq("dynamic_fe"))]
        if not frame.empty:
            save_line(frame, figure_dir / filename, title, {
                "actual": frame.groupby("report_date")["nco_rate"].mean(), "Dynamic FE recursive": frame.groupby("report_date")["prediction"].mean(),
            })
