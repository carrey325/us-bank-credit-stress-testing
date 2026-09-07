"""Repair-cycle R2 mean models with explicit forecast-time contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

MACRO_COLUMNS = ["gdp_growth", "unemployment_rate", "cre_price_growth", "house_price_growth", "bbb_spread", "short_rate", "mortgage_rate"]


def load_model_specs(root: Path) -> dict:
    with (root / "configs" / "model_specs.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _quarterly_grid(panel: pd.DataFrame) -> pd.DataFrame:
    """Insert explicit missing quarters and one forecast-only terminal quarter."""
    source = panel.copy()
    source["report_date"] = pd.to_datetime(source["report_date"])
    if source.duplicated(["bank_id", "segment", "report_date"]).any():
        raise ValueError("Credit panel has duplicate bank/segment/report-period keys")
    global_last = source["report_date"].max()
    frames = []
    for (bank_id, segment), group in source.groupby(["bank_id", "segment"], sort=False):
        end = group.report_date.max()
        if end == global_last:
            end += pd.offsets.QuarterEnd()
        dates = pd.date_range(group.report_date.min(), end, freq="QE")
        grid = pd.DataFrame({"bank_id": bank_id, "segment": segment, "report_date": dates})
        frames.append(grid.merge(group.assign(observed_credit_row=True), on=["bank_id", "segment", "report_date"], how="left", validate="one_to_one"))
    result = pd.concat(frames, ignore_index=True).sort_values(["bank_id", "segment", "report_date"])
    result["observed_credit_row"] = result["observed_credit_row"].eq(True)
    return result


def _adjacent_prior(frame: pd.DataFrame, column: str, groups: list[str]) -> pd.Series:
    prior_date = frame.groupby(groups, sort=False)["report_date"].shift(1)
    adjacent = prior_date.eq(frame["report_date"] - pd.offsets.QuarterEnd())
    return frame.groupby(groups, sort=False)[column].shift(1).where(adjacent)


def build_model_panel(credit_panel: pd.DataFrame, macro_panel: pd.DataFrame, fdic_noncurrent: pd.DataFrame | None = None, availability_days: int = 45) -> pd.DataFrame:
    """Align origin-period information to next-quarter targets without leakage."""
    if fdic_noncurrent is None:
        raise ValueError("R2 requires FDIC NCLNLS/LNLSNET historical noncurrent-loan input")
    panel = _quarterly_grid(credit_panel)
    macro = macro_panel.copy()
    macro["report_date"] = pd.to_datetime(macro["report_date"])
    panel = panel.merge(macro, on="report_date", how="left", validate="many_to_one")
    fdic = fdic_noncurrent.copy()
    fdic["bank_id"] = fdic["bank_id"].astype(str)
    fdic["report_date"] = pd.to_datetime(fdic["report_date"])
    panel["cert"] = panel["cert"].astype("string")
    panel = panel.merge(fdic, left_on=["cert", "report_date"], right_on=["bank_id", "report_date"], how="left", validate="many_to_one", suffixes=("", "_fdic")).drop(columns="bank_id_fdic")
    panel["npl"] = panel["fdic_noncurrent_loans"]
    panel["npl_rate"] = panel["fdic_noncurrent_ratio"]
    panel["allowance_coverage_r2"] = panel["allowance"] / panel["fdic_noncurrent_loans"].where(panel["fdic_noncurrent_loans"] > 0)
    panel = panel.sort_values(["bank_id", "segment", "report_date"]).copy()
    groups = ["bank_id", "segment"]
    prior_date = panel.groupby(groups, sort=False)["report_date"].shift(1)
    panel["origin_is_adjacent"] = prior_date.eq(panel["report_date"] - pd.offsets.QuarterEnd())
    panel["report_period"] = prior_date.where(panel["origin_is_adjacent"])
    panel["target_period"] = panel["report_date"]
    panel["available_at"] = panel["report_period"] + pd.to_timedelta(availability_days, unit="D")
    panel["forecast_origin"] = panel["available_at"]
    panel["nco_rate"] = panel["annualized_nco_rate"]
    origin_columns = {
        "annualized_nco_rate": "lagged_nco_rate", "npl_rate": "lagged_noncurrent_ratio",
        "allowance_coverage_r2": "lagged_allowance_coverage", "tier1_ratio": "lagged_tier1_ratio",
        "total_loans": "origin_total_loans", "eligible_for_model": "origin_eligible_for_model",
        "merger_recent_flag": "origin_merger_recent_flag", "cre_to_tier1": "origin_cre_to_tier1",
        "cre_share": "origin_cre_share", "exposure": "origin_exposure",
    }
    for source, target in origin_columns.items():
        panel[target] = _adjacent_prior(panel, source, groups)
    prior_total_loans = _adjacent_prior(panel, "total_loans", groups)
    origin_growth = panel["total_loans"] / prior_total_loans - 1
    panel["_origin_growth"] = origin_growth
    panel["lagged_loan_growth"] = _adjacent_prior(panel, "_origin_growth", groups)
    panel = panel.drop(columns="_origin_growth")
    # macro.py has already applied the availability lag; carry once to target.
    for column in [item for item in MACRO_COLUMNS if item in panel]:
        panel[f"lagged_{column}"] = _adjacent_prior(panel, column, groups)
    base_predictors = ["lagged_nco_rate", "lagged_noncurrent_ratio", "lagged_allowance_coverage", "lagged_loan_growth", "lagged_tier1_ratio"]
    panel["prediction_eligible"] = (
        panel["origin_is_adjacent"] & panel["origin_eligible_for_model"].eq(1)
        & panel["origin_merger_recent_flag"].eq(0) & panel[base_predictors].notna().all(axis=1)
    )
    panel["evaluation_eligible"] = panel["prediction_eligible"] & panel["nco_rate"].notna()
    panel["forecast_only"] = panel["prediction_eligible"] & panel["nco_rate"].isna()
    return panel


def _ols(y: np.ndarray, x: np.ndarray, clusters: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    beta = np.linalg.pinv(x.T @ x) @ x.T @ y
    resid = y - x @ beta
    bread = np.linalg.pinv(x.T @ x)
    if clusters is None:
        covariance = float(resid @ resid / max(len(y) - x.shape[1], 1)) * bread
    else:
        meat = np.zeros((x.shape[1], x.shape[1]))
        for cluster in pd.unique(clusters):
            mask = clusters == cluster
            score = x[mask].T @ resid[mask]
            meat += np.outer(score, score)
        g = len(pd.unique(clusters))
        correction = (g / max(g - 1, 1)) * ((len(y) - 1) / max(len(y) - x.shape[1], 1))
        covariance = correction * bread @ meat @ bread
    return beta, np.sqrt(np.clip(np.diag(covariance), 0, None)), resid


def _fit_entity_fe(data: pd.DataFrame, outcome: str, predictors: list[str]) -> dict:
    frame = data.dropna(subset=[outcome, *predictors]).copy()
    if frame.empty:
        raise ValueError("No complete observations for fixed-effects fit")
    frame["entity"] = frame["bank_id"].astype(str) + "::" + frame["segment"].astype(str)
    means = frame.groupby("entity")[[outcome, *predictors]].mean()
    demeaned = frame.join(means, on="entity", rsuffix="_mean")
    y = (demeaned[outcome] - demeaned[f"{outcome}_mean"]).to_numpy(float)
    x = np.column_stack([(demeaned[c] - demeaned[f"{c}_mean"]).to_numpy(float) for c in predictors])
    beta, se, _ = _ols(y, x, demeaned["bank_id"].astype(str).to_numpy())
    singular = np.linalg.svd(x, compute_uv=False)
    return {"beta": beta, "se": se, "predictors": predictors, "entity_means": means, "nobs": len(frame), "entities": len(means), "rank": int(np.linalg.matrix_rank(x)), "columns": x.shape[1], "condition_number": float(singular.max() / singular.min()) if singular.min() > 0 else np.inf}


def _predict_entity_fe(fit: dict, data: pd.DataFrame, outcome: str) -> pd.DataFrame:
    """Predict without requiring an observed target outcome."""
    frame = data.dropna(subset=fit["predictors"]).copy()
    frame["entity"] = frame["bank_id"].astype(str) + "::" + frame["segment"].astype(str)
    frame["unseen_entity"] = ~frame["entity"].isin(fit["entity_means"].index)
    frame = frame.loc[~frame["unseen_entity"]].copy()
    means = fit["entity_means"].reindex(frame["entity"])
    x = frame[fit["predictors"]].to_numpy(float)
    intercept = means[outcome].to_numpy(float) - means[fit["predictors"]].to_numpy(float) @ fit["beta"]
    frame["prediction"] = intercept + x @ fit["beta"]
    return frame


def _metrics(predictions: pd.DataFrame, weight_column: str | None = None) -> dict:
    scored = predictions.dropna(subset=["nco_rate", "prediction"]).copy()
    if weight_column is None:
        weights = np.ones(len(scored), dtype=float)
        label = "equal_observation"
    else:
        weights = pd.to_numeric(scored[weight_column], errors="coerce").to_numpy(float)
        valid = np.isfinite(weights) & (weights > 0)
        scored, weights = scored.loc[valid], weights[valid]
        label = "target_exposure_weighted"
    weights = weights / weights.sum()
    error = scored["nco_rate"].to_numpy(float) - scored["prediction"].to_numpy(float)
    actual = scored["nco_rate"].to_numpy(float)
    mean_actual = float(np.sum(weights * actual))
    sse = float(np.sum(weights * error ** 2))
    sst = float(np.sum(weights * (actual - mean_actual) ** 2))
    return {"n": len(scored), "weighting": label, "rmse": float(np.sqrt(sse)), "mae": float(np.sum(weights * np.abs(error))), "bias": float(np.sum(weights * error)), "r2_vs_test_mean": float(1 - sse / sst) if sst > 0 else np.nan, "weighted_sse": sse}


def _eligible_frame(panel: pd.DataFrame, spec: dict) -> pd.DataFrame:
    frames = []
    for segment in spec["primary_segments"]:
        predictors = ["lagged_nco_rate", *spec["dynamic_fe_spec"]["bank_features"], *spec["dynamic_fe_spec"]["segment_macro_variables"][segment]]
        data = panel[panel.segment.eq(segment)].copy()
        data["sample_predictors"] = "|".join(predictors)
        data["predictor_complete"] = data[predictors].notna().all(axis=1)
        data["prediction_eligible"] &= data["predictor_complete"]
        data["evaluation_eligible"] = data["prediction_eligible"] & data["nco_rate"].notna()
        frames.append(data)
    return pd.concat(frames, ignore_index=True)


def run_oos_models(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    spec = load_model_specs(root)
    eligible = _eligible_frame(panel, spec)
    output = root / "outputs" / "models"
    (output / "ar").mkdir(parents=True, exist_ok=True)
    (output / "dynamic_fe").mkdir(parents=True, exist_ok=True)
    metric_rows, coefficients = [], []
    predictions = {"ar": [], "dynamic_fe": []}
    for window_id, window in enumerate(spec["oos_windows"], start=1):
        for segment in spec["primary_segments"]:
            segment_data = eligible[eligible.segment.eq(segment)]
            train = segment_data[segment_data.target_period.between(pd.Timestamp(window["train_start"]), pd.Timestamp(window["train_end"])) & segment_data.evaluation_eligible]
            test = segment_data[segment_data.target_period.between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"])) & segment_data.prediction_eligible]
            predictors = segment_data.sample_predictors.iloc[0].split("|")
            model_predictions = {}
            for model, cols in [("ar", ["lagged_nco_rate"]), ("dynamic_fe", predictors)]:
                fit = _fit_entity_fe(train, "nco_rate", cols)
                predicted = _predict_entity_fe(fit, test, "nco_rate")
                predicted["window"], predicted["model"] = window_id, model
                predictions[model].append(predicted)
                model_predictions[model] = predicted
                for weight in [None, "exposure"]:
                    metric_rows.append({"window": window_id, "segment": segment, "model": model, **window, **_metrics(predicted, weight)})
                if model == "dynamic_fe":
                    coefficients.extend({"window": window_id, "segment": segment, "term": term, "estimate": estimate, "clustered_se": se, "ci95_low": estimate - 1.96 * se, "ci95_high": estimate + 1.96 * se, "nobs": fit["nobs"], "entities": fit["entities"], "matrix_rank": fit["rank"], "matrix_columns": fit["columns"], "condition_number": fit["condition_number"], "recursive_stable_if_lag": bool(abs(estimate) < 1) if term == "lagged_nco_rate" else pd.NA} for term, estimate, se in zip(fit["predictors"], fit["beta"], fit["se"], strict=True))
            keys = ["bank_id", "segment", "forecast_origin", "target_period"]
            ar = model_predictions["ar"].dropna(subset=["nco_rate"]).set_index(keys).sort_index()
            fe = model_predictions["dynamic_fe"].dropna(subset=["nco_rate"]).set_index(keys).sort_index()
            if not ar.index.equals(fe.index):
                raise ValueError(f"AR and Dynamic FE scoring keys differ in window {window_id} {segment}")
            recent = metric_rows[-4:]
            ar_sse_by_weight = {row["weighting"]: row["weighted_sse"] for row in recent if row["model"] == "ar"}
            for row in recent:
                baseline_sse = ar_sse_by_weight[row["weighting"]]
                row["sse_improvement_vs_ar"] = 0.0 if row["model"] == "ar" else (1 - row["weighted_sse"] / baseline_sse if baseline_sse > 0 else np.nan)
                row["common_scoring_keys_verified"] = True
    metrics = pd.DataFrame(metric_rows)
    coefficient_frame = pd.DataFrame(coefficients)
    ar_frame, fe_frame = pd.concat(predictions["ar"], ignore_index=True), pd.concat(predictions["dynamic_fe"], ignore_index=True)
    metrics[metrics.model.eq("ar")].to_csv(output / "ar" / "oos_metrics.csv", index=False)
    ar_frame.to_parquet(output / "ar" / "predictions.parquet", index=False)
    metrics[metrics.model.eq("dynamic_fe")].to_csv(output / "dynamic_fe" / "oos_metrics.csv", index=False)
    fe_frame.to_parquet(output / "dynamic_fe" / "predictions.parquet", index=False)
    coefficient_frame.to_csv(output / "dynamic_fe" / "coefficients.csv", index=False)
    return eligible, metrics, coefficient_frame


def run_split_panel_jackknife(eligible: pd.DataFrame, root: Path) -> pd.DataFrame:
    spec, rows = load_model_specs(root), []
    for segment in spec["primary_segments"]:
        data = eligible[eligible.segment.eq(segment) & eligible.evaluation_eligible].copy()
        predictors = data.sample_predictors.iloc[0].split("|")
        periods = data.target_period.sort_values().unique()
        midpoint = periods[len(periods) // 2]
        fits = {"full": _fit_entity_fe(data, "nco_rate", predictors), "first_half": _fit_entity_fe(data[data.target_period <= midpoint], "nco_rate", predictors), "second_half": _fit_entity_fe(data[data.target_period > midpoint], "nco_rate", predictors)}
        for index, term in enumerate(predictors):
            full, first, second = (fits[name]["beta"][index] for name in ["full", "first_half", "second_half"])
            rows.append({"segment": segment, "term": term, "full_fe": full, "first_half_fe": first, "second_half_fe": second, "spj_bias_corrected_diagnostic": 2 * full - (first + second) / 2, "diagnostic_only": True})
    result = pd.DataFrame(rows)
    result.to_csv(root / "outputs" / "models" / "dynamic_fe" / "split_panel_jackknife.csv", index=False)
    return result


def _two_way_demean(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame[columns].astype(float).copy()
    for _ in range(100):
        prior = out.to_numpy().copy()
        out -= out.groupby(frame.bank_id.astype(str)).transform("mean")
        out -= out.groupby(frame.target_period).transform("mean")
        out += out.mean()
        if np.abs(out.to_numpy() - prior).max() < 1e-10:
            break
    return out


def _prepare_cre_interaction_data(panel: pd.DataFrame, spec: dict, exposure: str | None = None) -> pd.DataFrame:
    data, exposure = panel[panel.segment.eq(spec["segment"])].copy(), exposure or spec["exposure"]
    source_column = f"origin_{exposure}"
    if source_column not in data:
        data = data.sort_values(["bank_id", "report_date"]).copy()
        data["report_period"] = data.groupby("bank_id").report_date.shift(1)
        adjacent = data.report_period.eq(data.report_date - pd.offsets.QuarterEnd())
        data[source_column] = data.groupby("bank_id")[exposure].shift(1).where(adjacent)
        data["target_period"] = data.report_date
        data["available_at"] = data.report_period + pd.to_timedelta(45, unit="D")
        data["forecast_origin"] = data.available_at
        data["prediction_eligible"] = data.get("eligible_for_model", 0).eq(1)
    data["exposure_as_of_date"] = data.report_period
    data["lagged_exposure"] = data[source_column]
    data["cre_price_shock_growth"] = data.lagged_cre_price_growth if "lagged_cre_price_growth" in data else data[spec["shock"]]
    data["cre_price_decline"] = -data.cre_price_shock_growth
    data["exposure_x_cre_price_shock"] = data.lagged_exposure * data.cre_price_shock_growth
    return data[data.prediction_eligible].copy()


def _fit_interaction_variant(data: pd.DataFrame, variant: str, exposure_definition: str, include_exposure_main: bool = True) -> pd.DataFrame:
    controls = ["lagged_nco_rate", "lagged_noncurrent_ratio", "lagged_allowance_coverage", "lagged_loan_growth"]
    terms = [*controls, *(["lagged_exposure"] if include_exposure_main else []), "exposure_x_cre_price_shock"]
    data = data.dropna(subset=["nco_rate", *terms]).copy()
    if not data.exposure_as_of_date.le(data.forecast_origin).all():
        raise ValueError("CRE interaction exposure date is after its forecast origin")
    demeaned = _two_way_demean(data, ["nco_rate", *terms])
    x = demeaned[terms].to_numpy(float)
    beta, se, _ = _ols(demeaned.nco_rate.to_numpy(float), x, data.bank_id.astype(str).to_numpy())
    return pd.DataFrame({"variant": variant, "term": terms, "estimate": beta, "bank_clustered_se": se, "ci95_low": beta - 1.96 * se, "ci95_high": beta + 1.96 * se, "nobs": len(data), "banks": data.bank_id.nunique(), "matrix_rank": int(np.linalg.matrix_rank(x)), "matrix_columns": x.shape[1], "exposure_definition": exposure_definition, "exposure_timing": "report_period_at_or_before_forecast_origin", "shock_definition": "CRE year-over-year price growth; decline magnitude equals negative growth", "interaction_sign_for_decline": -beta, "max_exposure_as_of_date": data.exposure_as_of_date.max(), "exposure_after_forecast_origin_count": 0})


def run_cre_interaction(panel: pd.DataFrame, root: Path) -> pd.DataFrame:
    spec = load_model_specs(root)["cre_interaction_spec"]
    frames = [_fit_interaction_variant(_prepare_cre_interaction_data(panel, spec), "primary", spec["exposure"]), _fit_interaction_variant(_prepare_cre_interaction_data(panel, spec, "cre_share"), "cre_share_alternative", "cre_share")]
    pre = _prepare_cre_interaction_data(panel, spec)
    fixed = pre[pre.report_period.le(pd.Timestamp("2021-12-31"))].sort_values("report_period").groupby("bank_id").tail(1)[["bank_id", "lagged_exposure", "exposure_as_of_date"]]
    post = pre[pre.target_period.gt(pd.Timestamp("2021-12-31"))].drop(columns=["lagged_exposure", "exposure_as_of_date"]).merge(fixed, on="bank_id", how="left", validate="many_to_one")
    post["exposure_x_cre_price_shock"] = post.lagged_exposure * post.cre_price_shock_growth
    if not post.dropna(subset=["nco_rate", "lagged_exposure"]).empty:
        # A bank-specific exposure frozen at 2021Q4 is absorbed by bank FE. Its
        # main effect is omitted only in this fixed-exposure robustness variant.
        frames.append(_fit_interaction_variant(post, "pre_2022_exposure_forward", spec["exposure"], include_exposure_main=False))
    result = pd.concat(frames, ignore_index=True)
    path = root / "outputs" / "models" / "cre_interaction"
    path.mkdir(parents=True, exist_ok=True)
    result.to_csv(path / "interaction_coefficients.csv", index=False)
    primary = result[(result.variant == "primary") & (result.term == "exposure_x_cre_price_shock")].iloc[0]
    (path / "result_status.md").write_text("# CRE concentration interaction\n\nThe primary regression includes bank and quarter fixed effects, lagged controls, the time-varying lagged CRE/Tier1 main effect, and its interaction with CRE year-over-year price growth. Quarter FE absorb the national shock main effect; identification is cross-sectional and is not presented as strictly causal. " f"The primary growth interaction estimate is {primary.estimate:.8g} with bank-clustered SE {primary.bank_clustered_se:.8g} and 95% CI [{primary.ci95_low:.8g}, {primary.ci95_high:.8g}]. For a decline-magnitude convention the sign is reversed, not reinterpreted as new evidence. The CRE-share and forward-used pre-2022 exposure variants were pre-authorized; no significance search was performed.\n", encoding="utf-8")
    return result
