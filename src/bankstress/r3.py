"""Minimal R3 tail and historical validation under the repair-cycle contract.

This module deliberately evaluates only one-step conditional quantiles and
conditional-mean recursive paths.  A recursively fed fixed quantile is emitted
as sensitivity evidence and is never converted into a multi-period loss
distribution or cumulative-loss quantile.
"""

from __future__ import annotations

from dataclasses import dataclass
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.regression.quantile_regression import IterationLimitWarning, QuantReg

from bankstress.modeling import (
    _eligible_frame,
    _fit_entity_fe,
    _predict_entity_fe,
    load_model_specs,
)


KEYS = ["bank_id", "segment", "forecast_origin", "target_period"]
MACRO_PREFIXES = (
    "lagged_gdp_", "lagged_unemployment_", "lagged_cre_price_",
    "lagged_house_price_", "lagged_bbb_", "lagged_short_", "lagged_mortgage_",
)
USE_VALUES = {"ALLOWED", "DIAGNOSTIC_ONLY", "UNAVAILABLE"}
FROZEN_CONTROL_SOURCES = {
    "lagged_noncurrent_ratio": "npl_rate",
    "lagged_allowance_coverage": "allowance_coverage_r2",
    "lagged_tier1_ratio": "tier1_ratio",
}


@dataclass
class QuantileFit:
    result: Any
    predictors: list[str]
    bank_levels: list[str]
    reference_bank: str
    quantile: float
    iterations: int
    converged: bool
    warning: str | None


def prediction_target_dictionary() -> list[dict[str, Any]]:
    """Return the authoritative R3 target taxonomy."""
    return [
        {"target_id": "one_step_conditional_mean", "nominal_coverage": None, "status": "EVALUATED",
         "definition": "One-quarter-ahead conditional mean point forecast."},
        {"target_id": "one_step_q90_upper_quantile", "nominal_coverage": 0.90, "nominal_exceedance_rate": 0.10,
         "status": "EVALUATED", "definition": "One-quarter-ahead upper conditional Q0.90."},
        {"target_id": "one_step_q50_q90_band", "nominal_coverage": 0.40, "status": "EVALUATED",
         "definition": "Band between one-step Q0.50 and Q0.90; not a two-sided 90% interval."},
        {"target_id": "residual_calibrated_two_sided_90_interval", "nominal_coverage": 0.90,
         "status": "NOT_EVALUATED", "definition": "Two-sided residual-calibrated interval, distinct from Q0.90."},
        {"target_id": "conditional_mean_recursive_path", "nominal_coverage": None, "status": "EVALUATED",
         "definition": "Plug-in recursive point path conditional on a supplied macro path; not asserted to be an exact expectation."},
        {"target_id": "multi_period_cumulative_loss_q90", "nominal_coverage": 0.90, "status": "NOT_EVALUATED",
         "definition": "Q0.90 of a joint multi-period cumulative-loss distribution; fixed-Q0.90 feedback is not this target."},
    ]


def validate_target_dictionary(rows: list[dict[str, Any]]) -> None:
    indexed = {row["target_id"]: row for row in rows}
    if indexed["one_step_q90_upper_quantile"].get("nominal_exceedance_rate") != 0.10:
        raise ValueError("One-step Q0.90 must carry a nominal 10% exceedance rate")
    if indexed["one_step_q50_q90_band"].get("nominal_coverage") != 0.40:
        raise ValueError("Q0.50-Q0.90 band must be labelled as 40% coverage")
    if indexed["residual_calibrated_two_sided_90_interval"]["target_id"] == "one_step_q90_upper_quantile":
        raise ValueError("Two-sided residual interval cannot be labelled as the Q0.90 upper quantile")
    if indexed["multi_period_cumulative_loss_q90"]["status"] != "NOT_EVALUATED":
        raise ValueError("Minimal R3 did not evaluate a multi-period cumulative-loss Q0.90")


def assert_not_cumulative_q90(target_type: str) -> None:
    if target_type != "recursive_quantile_sensitivity_not_distribution":
        raise ValueError("Fixed-quantile feedback may only be labelled recursive quantile sensitivity")


def quarter_sequence(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    values = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="Q").to_timestamp(how="end").normalize()
    periods = values.to_period("Q")
    if len(periods) > 1 and not np.all(np.diff(periods.astype(int)) == 1):
        raise ValueError("Historical validation grid is not quarter-contiguous")
    return pd.DatetimeIndex(values)


def pinball_loss(actual: pd.Series, prediction: pd.Series, tau: float) -> float:
    error = actual.to_numpy(float) - prediction.to_numpy(float)
    return float(np.maximum(tau * error, (tau - 1) * error).mean())


def _design(data: pd.DataFrame, predictors: list[str], banks: list[str], reference: str) -> pd.DataFrame:
    x = data[predictors].astype(float).copy()
    bank = data.bank_id.astype(str)
    for level in banks:
        if level != reference:
            x[f"bank::{level}"] = (bank == level).astype(float)
    x.insert(0, "const", 1.0)
    return x


def fit_quantile(train: pd.DataFrame, predictors: list[str], tau: float, spec: dict[str, Any]) -> QuantileFit:
    frame = train.dropna(subset=["nco_rate", *predictors]).copy()
    banks = sorted(frame.bank_id.astype(str).unique())
    if len(banks) < 2:
        raise ValueError("Quantile fit requires at least two banks")
    caught: list[warnings.WarningMessage]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", IterationLimitWarning)
        result = QuantReg(frame.nco_rate.to_numpy(float), _design(frame, predictors, banks, banks[0]).to_numpy(float)).fit(
            q=tau, max_iter=int(spec["max_iter"]), p_tol=float(spec["p_tol"])
        )
    iteration_warning = next((str(item.message) for item in caught if issubclass(item.category, IterationLimitWarning)), None)
    iterations = int(result.iterations)
    return QuantileFit(result, predictors, banks, banks[0], tau, iterations,
                       iteration_warning is None and iterations < int(spec["max_iter"]), iteration_warning)


def predict_quantile(fit: QuantileFit, data: pd.DataFrame) -> pd.DataFrame:
    """Predict without conditioning eligibility on the realized target."""
    frame = data.dropna(subset=fit.predictors).copy()
    frame = frame[frame.bank_id.astype(str).isin(fit.bank_levels)].copy()
    frame["prediction"] = fit.result.predict(
        _design(frame, fit.predictors, fit.bank_levels, fit.reference_bank).to_numpy(float)
    )
    return frame


def _score_quantile(frame: pd.DataFrame, tau: float) -> dict[str, Any]:
    scored = frame.dropna(subset=["nco_rate", "prediction"]).copy()
    exceed = scored.nco_rate > scored.prediction
    return {
        "n": len(scored), "pinball_loss": pinball_loss(scored.nco_rate, scored.prediction, tau),
        "exceedance_count": int(exceed.sum()), "empirical_exceedance_rate": float(exceed.mean()),
        "nominal_exceedance_rate": 1 - tau,
        "zero_exceedance_is_automatic_success": False,
    }


def _rearrange(frames: dict[float, pd.DataFrame], prediction_column: str = "prediction_raw") -> tuple[dict[float, pd.DataFrame], int]:
    common = set.intersection(*(set(map(tuple, frame[KEYS].to_numpy())) for frame in frames.values()))
    ordered = sorted(common)
    matrix = np.column_stack([
        frames[tau].set_index(KEYS).loc[ordered, prediction_column].to_numpy(float) for tau in sorted(frames)
    ])
    crossing = int(np.any(np.diff(matrix, axis=1) < 0, axis=1).sum())
    repaired = np.sort(matrix, axis=1)
    output = {}
    for column, tau in enumerate(sorted(frames)):
        item = frames[tau].set_index(KEYS).loc[ordered].copy()
        item["prediction_rearranged"] = repaired[:, column]
        output[tau] = item.reset_index()
    return output, crossing


def run_one_step_quantiles(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = _eligible_frame(panel, spec)
    predictions, metrics, fits = [], [], []
    taus = [float(item) for item in spec["quantiles"]]
    for window_id, window in enumerate(spec["oos_windows"], start=1):
        for segment in spec["primary_segments"]:
            data = eligible[eligible.segment.eq(segment)]
            predictors = data.sample_predictors.iloc[0].split("|")
            train = data[data.target_period.between(pd.Timestamp(window["train_start"]), pd.Timestamp(window["train_end"])) & data.evaluation_eligible].copy()
            test = data[data.target_period.between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"])) & data.prediction_eligible].copy()
            families = {"dynamic_quantile": predictors, "ar_quantile": ["lagged_nco_rate"]}
            family_frames: dict[str, dict[float, pd.DataFrame]] = {}
            for family, columns in families.items():
                raw = {}
                for tau in taus:
                    fit = fit_quantile(train, columns, tau, spec["quantile_spec"])
                    predicted = predict_quantile(fit, test)
                    predicted["prediction_raw"] = predicted.pop("prediction")
                    raw[tau] = predicted
                    fits.append({"window": window_id, "segment": segment, "model_family": family, "tau": tau,
                                 "iterations": fit.iterations, "converged": fit.converged, "warning": fit.warning,
                                 "training_observations": len(train.dropna(subset=["nco_rate", *columns])),
                                 "training_banks": train.dropna(subset=["nco_rate", *columns]).bank_id.nunique(),
                                 "feature_count_including_bank_effects": len(fit.result.params)})
                family_frames[family], crossing = _rearrange(raw)
                for diagnostic in fits[-len(taus):]:
                    diagnostic["crossing_rows_family_window"] = crossing
                for tau, frame in family_frames[family].items():
                    for version, column in (("PRE_REARRANGEMENT", "prediction_raw"), ("POST_REARRANGEMENT", "prediction_rearranged")):
                        item = frame.copy()
                        item["prediction"] = item[column]
                        item["window"], item["model_family"], item["tau"], item["prediction_version"] = window_id, family, tau, version
                        item["target_type"] = f"one_step_q{int(tau * 100):02d}_conditional_quantile"
                        predictions.append(item[[*KEYS, "nco_rate", "prediction", "prediction_raw", "prediction_rearranged", "window", "model_family", "tau", "prediction_version", "target_type"]])
            # Fair same-tau scoring uses the intersection of dynamic and AR keys.
            for tau in taus:
                for version, column in (("PRE_REARRANGEMENT", "prediction_raw"), ("POST_REARRANGEMENT", "prediction_rearranged")):
                    complex_frame = family_frames["dynamic_quantile"][tau]
                    baseline_frame = family_frames["ar_quantile"][tau]
                    common = complex_frame[KEYS].merge(baseline_frame[KEYS], on=KEYS).drop_duplicates()
                    for family, frame in (("dynamic_quantile", complex_frame), ("ar_quantile", baseline_frame)):
                        scored = common.merge(frame, on=KEYS, validate="one_to_one")
                        scored["prediction"] = scored[column]
                        metrics.append({"window": window_id, "segment": segment, "model_family": family,
                                        "baseline_family": "ar_quantile", "tau": tau, "prediction_version": version,
                                        "common_scoring_keys_verified": True, **window, **_score_quantile(scored, tau)})
            low = family_frames["dynamic_quantile"][0.5]
            high = family_frames["dynamic_quantile"][0.9]
            band = low[KEYS + ["nco_rate", "prediction_rearranged"]].merge(
                high[KEYS + ["prediction_rearranged"]], on=KEYS, suffixes=("_q50", "_q90"), validate="one_to_one"
            ).dropna(subset=["nco_rate"])
            inside = band.nco_rate.between(band.prediction_rearranged_q50, band.prediction_rearranged_q90)
            metrics.append({"window": window_id, "segment": segment, "model_family": "dynamic_quantile_q50_q90_band",
                            "baseline_family": None, "tau": np.nan, "prediction_version": "POST_REARRANGEMENT",
                            "n": len(band), "empirical_coverage": float(inside.mean()), "nominal_coverage": 0.40,
                            "common_scoring_keys_verified": True, **window})
    prediction_frame, metric_frame, fit_frame = pd.concat(predictions, ignore_index=True), pd.DataFrame(metrics), pd.DataFrame(fits)
    pooled = []
    for (segment, family, tau, version), group in prediction_frame.groupby(
        ["segment", "model_family", "tau", "prediction_version"], sort=True
    ):
        pooled.append({"window": 0, "segment": segment, "model_family": family,
                       "baseline_family": "ar_quantile", "tau": tau, "prediction_version": version,
                       "common_scoring_keys_verified": True, "train_start": spec["oos_windows"][0]["train_start"],
                       "train_end": "EXPANDING", "test_start": spec["oos_windows"][0]["test_start"],
                       "test_end": spec["oos_windows"][-1]["test_end"], **_score_quantile(group, tau)})
    metric_frame = pd.concat([metric_frame, pd.DataFrame(pooled)], ignore_index=True, sort=False)
    # Retain the legacy read schema so invalid downstream audit code can inspect
    # (and reject) stale Batch 5 deliverables without mistaking R3 results for
    # those deliverables.  Only the post-rearrangement dynamic rows receive the
    # historical quantile_* model labels.
    prediction_frame["report_date"] = prediction_frame.target_period
    prediction_frame["model"] = prediction_frame.apply(
        lambda row: f"quantile_{row.tau}" if row.model_family == "dynamic_quantile" and row.prediction_version == "POST_REARRANGEMENT"
        else f"r3_{row.model_family}_q{int(row.tau * 100):02d}_{row.prediction_version.lower()}", axis=1
    )
    metric_frame["model"] = metric_frame.apply(
        lambda row: f"quantile_{row.tau}" if row.model_family == "dynamic_quantile" and row.prediction_version == "POST_REARRANGEMENT" and int(row.window) != 0
        else f"r3_{row.model_family}" + (f"_q{int(row.tau * 100):02d}" if pd.notna(row.tau) else ""), axis=1
    )
    metric_frame["metric"] = np.where(metric_frame.pinball_loss.notna(), "pinball_loss", "band_metrics")
    metric_frame["value"] = metric_frame.pinball_loss
    metric_frame = metric_frame.rename(columns={"n": "scored_n"})
    return prediction_frame, metric_frame, fit_frame


def _mean_scores(frame: pd.DataFrame) -> dict[str, Any]:
    scored = frame.dropna(subset=["nco_rate", "prediction"])
    error = scored.nco_rate - scored.prediction
    return {"n": len(scored), "rmse": float(np.sqrt(np.mean(error ** 2))),
            "mae": float(np.mean(np.abs(error))), "bias": float(np.mean(error))}


def _prepare_jump_off_state(train: pd.DataFrame, train_end: pd.Timestamp) -> tuple[pd.DataFrame, int]:
    """Build the recursive state from current train-end bank information.

    R2 target rows contain origin predictors that are already shifted once.  A
    historical forecast beginning in the following quarter must therefore use
    the current state columns on the train-end row, not those lagged predictors.
    """
    train_end = pd.Timestamp(train_end)
    candidates = train[train.target_period.eq(train_end)].copy()
    if candidates.duplicated("bank_id").any():
        raise ValueError(f"Duplicate train-end jump-off rows at {train_end.date()}")
    candidates["bank_id"] = candidates.bank_id.astype(str)
    for predictor, current_column in FROZEN_CONTROL_SOURCES.items():
        candidates[predictor] = candidates[current_column]
        candidates[f"{predictor}_source_period"] = train_end
    adjacent = candidates.report_period.eq(train_end - pd.offsets.QuarterEnd())
    candidates["lagged_loan_growth"] = (
        candidates.total_loans / candidates.origin_total_loans - 1
    ).where(adjacent & candidates.origin_total_loans.gt(0))
    candidates["lagged_loan_growth_source_period"] = train_end
    candidates["lagged_loan_growth_prior_component_source_period"] = candidates.report_period.where(adjacent)
    required = ["nco_rate", *FROZEN_CONTROL_SOURCES, "lagged_loan_growth"]
    valid = candidates[required].notna().all(axis=1)
    return candidates.loc[valid].copy(), int((~valid).sum())


def _historical_grid(panel: pd.DataFrame, segment: str, window: dict[str, str], jump: pd.DataFrame,
                     predictors: list[str]) -> pd.DataFrame:
    dates = quarter_sequence(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"]))
    banks = sorted(jump.bank_id.astype(str).unique())
    grid = pd.MultiIndex.from_product([banks, dates], names=["bank_id", "target_period"]).to_frame(index=False)
    grid["segment"] = segment
    source = panel[panel.segment.eq(segment)].copy()
    source.bank_id = source.bank_id.astype(str)
    actual = source[["bank_id", "segment", "target_period", "nco_rate", "lagged_nco_rate", "forecast_origin"]].drop_duplicates(["bank_id", "segment", "target_period"])
    grid = grid.merge(actual, on=["bank_id", "segment", "target_period"], how="left", validate="one_to_one")
    grid["report_date"] = grid.target_period
    macro_terms = [term for term in predictors if term.startswith(MACRO_PREFIXES)]
    for term in macro_terms:
        by_date = source.groupby("target_period")[term].first()
        grid[term] = grid.target_period.map(by_date)
    frozen_terms = [term for term in predictors if term != "lagged_nco_rate" and term not in macro_terms]
    latest = jump.set_index(jump.bank_id.astype(str))
    for term in frozen_terms:
        grid[term] = grid.bank_id.map(latest[term])
        source_column = f"{term}_source_period"
        if source_column not in latest:
            raise ValueError(f"Frozen historical control lacks source-period lineage: {term}")
        grid[source_column] = grid.bank_id.map(latest[source_column])
    balance_column = "origin_exposure" if "origin_exposure" in jump else "exposure"
    grid["frozen_balance"] = grid.bank_id.map(latest[balance_column])
    grid["frozen_balance_source_period"] = grid.bank_id.map(latest.report_period if balance_column == "origin_exposure" else latest.target_period)
    grid["bank_controls_source_period"] = grid.bank_id.map(latest.target_period)
    grid["bank_controls_frozen"] = True
    return grid


def _recursive_path(fit: Any, kind: str, grid: pd.DataFrame, jump: pd.DataFrame,
                    target_type: str) -> pd.DataFrame:
    if kind == "quantile":
        assert_not_cumulative_q90(target_type)
    state = dict(zip(jump.bank_id.astype(str), jump.nco_rate, strict=True))
    pieces = []
    for target, current in grid.groupby("target_period", sort=True):
        current = current.copy()
        current["lagged_nco_rate"] = current.bank_id.map(state)
        current["lagged_nco_rate_source_period"] = pd.Timestamp(target) - pd.offsets.QuarterEnd()
        current["lagged_nco_rate_source_type"] = np.where(
            pd.Timestamp(target) == grid.target_period.min(), "ACTUAL_JUMP_OFF", "MODELED_RECURSIVE"
        )
        predicted = _predict_entity_fe(fit, current, "nco_rate") if kind == "mean" else predict_quantile(fit, current)
        # Preserve the full path grid even when a supplied macro-path feature is
        # unavailable.  Such a row is explicitly unavailable, not silently
        # dropped or imputed; the last modeled state remains the next lag.
        payload = predicted[["bank_id", "prediction"]].copy()
        payload.bank_id = payload.bank_id.astype(str)
        current.bank_id = current.bank_id.astype(str)
        current = current.drop(columns="prediction", errors="ignore").merge(payload, on="bank_id", how="left", validate="one_to_one")
        current["prediction_available"] = current.prediction.notna()
        current["prediction_unavailable_reason"] = np.where(
            current.prediction_available, None, "SUPPLIED_MACRO_PATH_OR_REQUIRED_FEATURE_UNAVAILABLE"
        )
        available = current[current.prediction_available]
        state.update(dict(zip(available.bank_id, available.prediction, strict=True)))
        pieces.append(current)
    result = pd.concat(pieces, ignore_index=True)
    result["target_type"] = target_type
    return result


def run_historical_validation(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = _eligible_frame(panel, spec)
    path_rows, metric_rows, support_rows = [], [], []
    for window in spec["pseudo_stress_windows"]:
        for segment in spec["primary_segments"]:
            data = eligible[eligible.segment.eq(segment)].copy()
            predictors = data.sample_predictors.iloc[0].split("|")
            train = data[data.target_period.le(pd.Timestamp(window["train_end"])) & data.evaluation_eligible].copy()
            if train.empty:
                raise ValueError(f"No historical training support for {window['name']} {segment}")
            jump_candidates = train[train.target_period.eq(pd.Timestamp(window["train_end"]))].copy()
            jump, jump_control_exclusions = _prepare_jump_off_state(train, pd.Timestamp(window["train_end"]))
            if jump.empty:
                raise ValueError(f"No valid jump-off state at {window['train_end']} for {window['name']} {segment}")
            grid = _historical_grid(panel, segment, window, jump, predictors)
            control_source_columns = [f"{term}_source_period" for term in spec["dynamic_fe_spec"]["bank_features"]]
            source_mismatches = int(sum(
                (~grid[column].eq(pd.Timestamp(window["train_end"]))).sum()
                for column in control_source_columns
            ))
            expected = len(jump) * len(quarter_sequence(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"])))
            support_rows.append({"pseudo_window": window["name"], "segment": segment,
                                 "requested_training_start": pd.Timestamp("2005-01-01"),
                                 "effective_training_start": train.target_period.min(), "training_end": train.target_period.max(),
                                 "training_quarters": train.target_period.nunique(), "training_banks": train.bank_id.nunique(),
                                 "features": len(predictors), "effective_training_samples": len(train),
                                 "jump_off_candidate_banks": len(jump_candidates),
                                 "jump_off_current_control_exclusions": jump_control_exclusions,
                                 "jump_off_banks": len(jump), "forecast_quarters": grid.target_period.nunique(),
                                 "expected_path_rows_per_model": expected,
                                 "gfc_2005_start_verified": bool(window["name"] != "GFC" or
                                                                 (panel[panel.segment.eq(segment)].target_period.min().year == 2005
                                                                  and train.target_period.min().year == 2005)),
                                 "bank_controls_frozen": bool(grid.bank_controls_frozen.all()),
                                 "jump_off_current_controls_verified": source_mismatches == 0,
                                 "frozen_control_source_mismatch_count": source_mismatches,
                                 "future_control_leakage_count": int((grid.bank_controls_source_period > pd.Timestamp(window["train_end"])).sum())})
            mean_fits = {"ar_mean": (_fit_entity_fe(train, "nco_rate", ["lagged_nco_rate"]), ["lagged_nco_rate"]),
                         "dynamic_fe": (_fit_entity_fe(train, "nco_rate", predictors), predictors)}
            source_future = data[data.target_period.between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"])) & data.prediction_eligible]
            for model_id, (fit, columns) in mean_fits.items():
                lag_index = fit["predictors"].index("lagged_nco_rate")
                lag_coefficient = float(fit["beta"][lag_index])
                recursive_stable = bool(np.isfinite(lag_coefficient) and abs(lag_coefficient) < 1)
                one_step = _predict_entity_fe(fit, source_future, "nco_rate")
                one_step["pseudo_window"], one_step["model_id"], one_step["validation_mode"] = window["name"], model_id, "ONE_STEP_ORIGIN_INFORMATION"
                metric_rows.append({"pseudo_window": window["name"], "segment": segment, "model_id": model_id,
                                    "validation_mode": "ONE_STEP_ORIGIN_INFORMATION", "metric_family": "modeled_rate_error", **_mean_scores(one_step)})
                recursive = _recursive_path(fit, "mean", grid, jump, "conditional_mean_recursive_path")
                recursive["pseudo_window"], recursive["model_id"], recursive["validation_mode"] = window["name"], model_id, "RECURSIVE_CONDITIONAL_MEAN"
                metric_rows.append({"pseudo_window": window["name"], "segment": segment, "model_id": model_id,
                                    "validation_mode": "RECURSIVE_CONDITIONAL_MEAN", "metric_family": "modeled_rate_error",
                                    "generated_n": len(recursive), "prediction_unavailable_n": int(recursive.prediction.isna().sum()),
                                    "lag_coefficient": lag_coefficient, "recursive_stable": recursive_stable,
                                    "jump_off_current_controls_verified": source_mismatches == 0,
                                    "frozen_control_source_mismatch_count": source_mismatches,
                                    "max_abs_prediction": float(recursive.prediction.abs().max()),
                                    "unscored_missing_actual_n": int(recursive.nco_rate.isna().sum()), **_mean_scores(recursive)})
                scored = recursive.dropna(subset=["nco_rate", "prediction", "frozen_balance"]).copy()
                scored["modeled_loss"] = scored.prediction * scored.frozen_balance / 4
                scored["actual_loss_same_frozen_balance"] = scored.nco_rate * scored.frozen_balance / 4
                cumulative = scored.groupby("bank_id")[["modeled_loss", "actual_loss_same_frozen_balance"]].sum()
                cumulative_error = cumulative.actual_loss_same_frozen_balance - cumulative.modeled_loss
                metric_rows.append({"pseudo_window": window["name"], "segment": segment, "model_id": model_id,
                                    "validation_mode": "RECURSIVE_CONDITIONAL_MEAN", "metric_family": "cumulative_modeled_loss_error_same_frozen_balance",
                                    "n": len(cumulative), "rmse": float(np.sqrt(np.mean(cumulative_error ** 2))),
                                    "mae": float(np.mean(np.abs(cumulative_error))), "bias": float(np.mean(cumulative_error))})
                path_rows.append(recursive)
            q90_fit = fit_quantile(train, predictors, 0.9, spec["quantile_spec"])
            q90 = _recursive_path(q90_fit, "quantile", grid, jump, "recursive_quantile_sensitivity_not_distribution")
            q90["pseudo_window"], q90["model_id"], q90["validation_mode"] = window["name"], "dynamic_quantile_q90", "RECURSIVE_QUANTILE_SENSITIVITY"
            q90_score = q90.dropna(subset=["nco_rate", "prediction"])
            metric_rows.append({"pseudo_window": window["name"], "segment": segment, "model_id": "dynamic_quantile_q90",
                                "validation_mode": "RECURSIVE_QUANTILE_SENSITIVITY", "metric_family": "diagnostic_one_period_rate_scoring",
                                "generated_n": len(q90), "prediction_unavailable_n": int(q90.prediction.isna().sum()),
                                "unscored_missing_actual_n": int(q90.nco_rate.isna().sum()), **_score_quantile(q90_score, 0.9)})
            path_rows.append(q90)
    paths, metrics, support = pd.concat(path_rows, ignore_index=True), pd.DataFrame(metric_rows), pd.DataFrame(support_rows)
    return paths, metrics, support


def build_model_use_registry(one_step_metrics: pd.DataFrame, historical_metrics: pd.DataFrame,
                             fit_diagnostics: pd.DataFrame, input_run_id: str, model_spec_hash: str,
                             evidence_files: list[str]) -> list[dict[str, Any]]:
    records = []
    for segment in sorted(one_step_metrics.segment.unique()):
        hist_segment = historical_metrics[historical_metrics.segment.eq(segment)]
        for model_id in ["ar_mean", "dynamic_fe"]:
            recursive = hist_segment[(hist_segment.model_id.eq(model_id)) & (hist_segment.validation_mode.eq("RECURSIVE_CONDITIONAL_MEAN")) &
                                     (hist_segment.metric_family.eq("modeled_rate_error"))]
            stable = bool(len(recursive) and recursive.prediction_unavailable_n.fillna(0).eq(0).all()
                          and recursive.recursive_stable.astype("boolean").fillna(False).all()
                          and recursive.jump_off_current_controls_verified.astype("boolean").fillna(False).all()
                          and recursive.frozen_control_source_mismatch_count.fillna(1).eq(0).all()
                          and np.isfinite(recursive.max_abs_prediction).all())
            records.append({"model_id": model_id, "segment": segment, "input_run_id": input_run_id,
                            "model_spec_hash": model_spec_hash, "descriptive_use": "ALLOWED",
                            "one_step_mean_use": "ALLOWED" if model_id == "ar_mean" else "DIAGNOSTIC_ONLY",
                            "one_step_tail_use": "UNAVAILABLE", "conditional_mean_stress_use": "ALLOWED" if stable else "DIAGNOSTIC_ONLY",
                            "multi_step_tail_distribution_use": "UNAVAILABLE", "evidence_files": evidence_files,
                            "limitations": ["Conditional macro path only; no claim of exact nonlinear expectation.",
                                            "Dynamic FE improved RMSE in only 1/8 R2 segment-window comparisons."] if model_id == "dynamic_fe" else ["Baseline model; not evidence of incremental macro benefit."],
                            "status_reason": ("Recursive path is complete and uses verified current train-end controls frozen with per-control source-quarter lineage; tail-distribution use was not evaluated."
                                              if stable else "Path rows are preserved, but at least one supplied macro-path feature is unavailable; formal stress use is not authorized.")})
        for family in ["ar_quantile", "dynamic_quantile"]:
            for tau in [0.5, 0.75, 0.9]:
                diag = fit_diagnostics[(fit_diagnostics.segment.eq(segment)) & (fit_diagnostics.model_family.eq(family)) & (fit_diagnostics.tau.eq(tau))]
                converged = bool(len(diag) and diag.converged.all())
                records.append({"model_id": f"{family}_q{int(tau*100):02d}", "segment": segment,
                                "input_run_id": input_run_id, "model_spec_hash": model_spec_hash,
                                "descriptive_use": "DIAGNOSTIC_ONLY", "one_step_mean_use": "UNAVAILABLE",
                                "one_step_tail_use": "DIAGNOSTIC_ONLY" if converged else "UNAVAILABLE",
                                "conditional_mean_stress_use": "UNAVAILABLE", "multi_step_tail_distribution_use": "UNAVAILABLE",
                                "evidence_files": evidence_files,
                                "limitations": ["Minimal R3 one-step evaluation only; calibration expansion was not evaluated.",
                                                "Fixed-quantile recursive feedback is sensitivity, not a cumulative-loss quantile."],
                                "status_reason": "One-step fits converged." if converged else "At least one one-step fit did not converge."})
    for row in records:
        for field in ["descriptive_use", "one_step_mean_use", "one_step_tail_use", "conditional_mean_stress_use", "multi_step_tail_distribution_use"]:
            if row[field] not in USE_VALUES:
                raise ValueError(f"Invalid model-use decision {row[field]}")
        if row["multi_step_tail_distribution_use"] != "UNAVAILABLE":
            raise ValueError("Minimal R3 cannot authorize multi-step tail-distribution use")
    return records
