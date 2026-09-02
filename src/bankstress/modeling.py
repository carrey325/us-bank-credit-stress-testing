"""Deterministic Batch 2 mean-model estimators without hidden statistical dependencies."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def load_model_specs(root: Path) -> dict:
    with (root / "configs" / "model_specs.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_model_panel(credit_panel: pd.DataFrame, macro_panel: pd.DataFrame, fdic_noncurrent: pd.DataFrame | None = None) -> pd.DataFrame:
    panel = credit_panel.copy()
    panel["report_date"] = pd.to_datetime(panel["report_date"])
    macro_panel = macro_panel.copy()
    macro_panel["report_date"] = pd.to_datetime(macro_panel["report_date"])
    panel = panel.merge(macro_panel, on="report_date", how="left", validate="many_to_one")
    panel = panel.sort_values(["bank_id", "segment", "report_date"]).copy()
    panel["nco_rate"] = panel["annualized_nco_rate"]
    if fdic_noncurrent is None:
        raise ValueError("Batch 2 requires FDIC NCLNLS/LNLSNET historical noncurrent-loan input")
    fdic = fdic_noncurrent.copy()
    fdic["bank_id"] = fdic["bank_id"].astype(str)
    fdic["report_date"] = pd.to_datetime(fdic["report_date"])
    panel["cert"] = panel["cert"].astype(str)
    panel = panel.merge(fdic, left_on=["cert", "report_date"], right_on=["bank_id", "report_date"], how="left", validate="many_to_one", suffixes=("", "_fdic"))
    panel = panel.drop(columns="bank_id_fdic")
    # `NCLNLS / LNLSNET` is a bank-level ratio supplied by one FDIC financial
    # record.  It has historical GFC coverage and never uses a segment denominator.
    panel["npl"] = panel["fdic_noncurrent_loans"]
    panel["npl_rate"] = panel["fdic_noncurrent_ratio"]
    bank_npl = panel.drop_duplicates(["bank_id", "report_date"])[["bank_id", "report_date", "npl_rate"]].sort_values(["bank_id", "report_date"])
    bank_npl["lagged_noncurrent_ratio"] = bank_npl.groupby("bank_id")["npl_rate"].shift(1)
    panel = panel.merge(bank_npl[["bank_id", "report_date", "lagged_noncurrent_ratio"]], on=["bank_id", "report_date"], how="left", validate="many_to_one")
    panel["lagged_nco_rate"] = panel.groupby(["bank_id", "segment"])["nco_rate"].shift(1)
    bank = panel.drop_duplicates(["bank_id", "report_date"])[["bank_id", "report_date", "allowance_coverage", "tier1_ratio", "total_loans"]].sort_values(["bank_id", "report_date"]).copy()
    bank["loan_growth_clean"] = bank.groupby("bank_id")["total_loans"].pct_change(fill_method=None)
    bank["lagged_allowance_coverage"] = bank.groupby("bank_id")["allowance_coverage"].shift(1)
    bank["lagged_tier1_ratio"] = bank.groupby("bank_id")["tier1_ratio"].shift(1)
    bank["lagged_loan_growth"] = bank.groupby("bank_id")["loan_growth_clean"].shift(1)
    panel = panel.merge(bank[["bank_id", "report_date", "lagged_allowance_coverage", "lagged_tier1_ratio", "lagged_loan_growth"]], on=["bank_id", "report_date"], how="left", validate="many_to_one")
    macro_columns = [column for column in ["gdp_growth", "unemployment_rate", "cre_price_growth", "house_price_growth", "bbb_spread", "short_rate", "mortgage_rate"] if column in panel]
    for column in macro_columns:
        panel[f"lagged_{column}"] = panel.groupby(["bank_id", "segment"])[column].shift(1)
    panel["forecast_origin"] = panel["report_date"] - pd.offsets.QuarterEnd()
    return panel


def _ols(y: np.ndarray, x: np.ndarray, clusters: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    beta = np.linalg.pinv(x.T @ x) @ x.T @ y
    resid = y - x @ beta
    bread = np.linalg.pinv(x.T @ x)
    if clusters is None:
        sigma2 = float(resid @ resid / max(len(y) - x.shape[1], 1))
        covariance = sigma2 * bread
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
    x = np.column_stack([(demeaned[column] - demeaned[f"{column}_mean"]).to_numpy(float) for column in predictors])
    beta, se, _ = _ols(y, x, demeaned["bank_id"].astype(str).to_numpy())
    return {"beta": beta, "se": se, "predictors": predictors, "entity_means": means, "nobs": len(frame), "entities": len(means)}


def _predict_entity_fe(fit: dict, data: pd.DataFrame, outcome: str) -> pd.DataFrame:
    frame = data.dropna(subset=[outcome, *fit["predictors"]]).copy()
    frame["entity"] = frame["bank_id"].astype(str) + "::" + frame["segment"].astype(str)
    common = frame["entity"].isin(fit["entity_means"].index)
    frame = frame.loc[common].copy()
    means = fit["entity_means"].reindex(frame["entity"])
    x = frame[fit["predictors"]].to_numpy(float)
    intercept = means[outcome].to_numpy(float) - means[fit["predictors"]].to_numpy(float) @ fit["beta"]
    frame["prediction"] = intercept + x @ fit["beta"]
    return frame


def _metrics(predictions: pd.DataFrame) -> dict:
    error = predictions["nco_rate"] - predictions["prediction"]
    ss_total = ((predictions["nco_rate"] - predictions["nco_rate"].mean()) ** 2).sum()
    return {"n": len(predictions), "rmse": float(np.sqrt((error ** 2).mean())), "mae": float(error.abs().mean()),
            "oos_r2": float(1 - (error ** 2).sum() / ss_total) if ss_total > 0 else np.nan, "bias": float(error.mean())}


def _eligible_frame(panel: pd.DataFrame, spec: dict) -> pd.DataFrame:
    macro_by_segment = spec["dynamic_fe_spec"]["segment_macro_variables"]
    features = spec["dynamic_fe_spec"]["bank_features"]
    frames: list[pd.DataFrame] = []
    for segment in spec["primary_segments"]:
        predictors = ["lagged_nco_rate", *features, *macro_by_segment[segment]]
        data = panel[panel["segment"].eq(segment)].copy()
        if spec["dynamic_fe_spec"]["exclude_merger_recent"]:
            data = data[data["merger_recent_flag"].eq(0)]
        data = data[data["eligible_for_model"].eq(1)].dropna(subset=["nco_rate", *predictors])
        data["sample_predictors"] = "|".join(predictors)
        frames.append(data)
    return pd.concat(frames, ignore_index=True)


def run_oos_models(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    spec = load_model_specs(root)
    eligible = _eligible_frame(panel, spec)
    output = root / "outputs" / "models"
    (output / "ar").mkdir(parents=True, exist_ok=True)
    (output / "dynamic_fe").mkdir(parents=True, exist_ok=True)
    metrics: list[dict] = []
    ar_predictions: list[pd.DataFrame] = []
    fe_predictions: list[pd.DataFrame] = []
    coefficients: list[dict] = []
    for window_id, window in enumerate(spec["oos_windows"], start=1):
        train = eligible[eligible["report_date"].between(pd.Timestamp(window["train_start"]), pd.Timestamp(window["train_end"]))]
        test = eligible[eligible["report_date"].between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"]))]
        for segment in spec["primary_segments"]:
            train_segment, test_segment = train[train.segment.eq(segment)], test[test.segment.eq(segment)]
            predictors = train_segment["sample_predictors"].iloc[0].split("|") if not train_segment.empty else []
            for model, cols, collector in [("ar", ["lagged_nco_rate"], ar_predictions), ("dynamic_fe", predictors, fe_predictions)]:
                fit = _fit_entity_fe(train_segment, "nco_rate", cols)
                predicted = _predict_entity_fe(fit, test_segment, "nco_rate")
                predicted["window"] = window_id
                predicted["model"] = model
                collector.append(predicted)
                metrics.append({"window": window_id, "segment": segment, "model": model, **window, **_metrics(predicted)})
                if model == "dynamic_fe":
                    coefficients.extend({"window": window_id, "segment": segment, "term": term, "estimate": estimate, "clustered_se": se,
                                         "nobs": fit["nobs"], "entities": fit["entities"]}
                                        for term, estimate, se in zip(fit["predictors"], fit["beta"], fit["se"], strict=True))
    metrics_frame = pd.DataFrame(metrics)
    comparison = metrics_frame.pivot(index=["window", "segment"], columns="model", values="rmse").reset_index()
    comparison["rmse_improvement_vs_ar"] = (comparison["ar"] - comparison["dynamic_fe"]) / comparison["ar"]
    metrics_frame = metrics_frame.merge(comparison[["window", "segment", "rmse_improvement_vs_ar"]], on=["window", "segment"], how="left")
    ar_frame, fe_frame, coefficient_frame = pd.concat(ar_predictions, ignore_index=True), pd.concat(fe_predictions, ignore_index=True), pd.DataFrame(coefficients)
    metrics_frame[metrics_frame.model.eq("ar")].to_csv(output / "ar" / "oos_metrics.csv", index=False)
    ar_frame.to_parquet(output / "ar" / "predictions.parquet", index=False)
    metrics_frame[metrics_frame.model.eq("dynamic_fe")].to_csv(output / "dynamic_fe" / "oos_metrics.csv", index=False)
    fe_frame.to_parquet(output / "dynamic_fe" / "predictions.parquet", index=False)
    coefficient_frame.to_csv(output / "dynamic_fe" / "coefficients.csv", index=False)
    return eligible, metrics_frame, coefficient_frame


def run_split_panel_jackknife(eligible: pd.DataFrame, root: Path) -> pd.DataFrame:
    spec = load_model_specs(root)
    rows: list[dict] = []
    for segment in spec["primary_segments"]:
        data = eligible[eligible.segment.eq(segment)].copy()
        predictors = data["sample_predictors"].iloc[0].split("|")
        midpoint = data.report_date.sort_values().unique()[len(data.report_date.unique()) // 2]
        fits = {"full": _fit_entity_fe(data, "nco_rate", predictors),
                "first_half": _fit_entity_fe(data[data.report_date <= midpoint], "nco_rate", predictors),
                "second_half": _fit_entity_fe(data[data.report_date > midpoint], "nco_rate", predictors)}
        for index, term in enumerate(predictors):
            full, first, second = (fits[name]["beta"][index] for name in ["full", "first_half", "second_half"])
            rows.append({"segment": segment, "term": term, "full_fe": full, "first_half_fe": first, "second_half_fe": second,
                         "spj_bias_corrected": 2 * full - (first + second) / 2})
    result = pd.DataFrame(rows)
    path = root / "outputs" / "models" / "dynamic_fe" / "split_panel_jackknife.csv"
    result.to_csv(path, index=False)
    return result


def _two_way_demean(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame[columns].astype(float).copy()
    for _ in range(100):
        prior = out.to_numpy().copy()
        out -= out.groupby(frame["bank_id"].astype(str)).transform("mean")
        out -= out.groupby(frame["report_date"]).transform("mean")
        out += out.mean()
        if np.abs(out.to_numpy() - prior).max() < 1e-10:
            break
    return out


def run_cre_interaction(panel: pd.DataFrame, root: Path) -> pd.DataFrame:
    spec = load_model_specs(root)["cre_interaction_spec"]
    data = panel[(panel.segment.eq(spec["segment"])) & (panel.eligible_for_model.eq(1)) & (panel.merger_recent_flag.eq(0))].copy()
    reference = pd.Timestamp(spec["pre_shock_reference"])
    exposure = data[data.report_date.le(reference)].sort_values("report_date").groupby("bank_id")[spec["exposure"]].last().rename("pre_shock_exposure")
    data = data.join(exposure, on="bank_id")
    data["cre_price_shock"] = data[spec["shock"]]
    data["exposure_x_cre_price_shock"] = data["pre_shock_exposure"] * data["cre_price_shock"]
    controls = ["lagged_nco_rate", "lagged_noncurrent_ratio", "lagged_allowance_coverage", "lagged_loan_growth"]
    terms = [*controls, "exposure_x_cre_price_shock"]
    data = data.dropna(subset=["nco_rate", *terms]).copy()
    demeaned = _two_way_demean(data, ["nco_rate", *terms])
    beta, se, _ = _ols(demeaned["nco_rate"].to_numpy(), demeaned[terms].to_numpy(), data["bank_id"].astype(str).to_numpy())
    result = pd.DataFrame({"term": terms, "estimate": beta, "bank_clustered_se": se, "nobs": len(data), "banks": data.bank_id.nunique(),
                           "exposure_definition": spec["exposure"], "shock": spec["shock"], "pre_shock_reference": reference.date().isoformat()})
    path = root / "outputs" / "models" / "cre_interaction"
    path.mkdir(parents=True, exist_ok=True)
    result.to_csv(path / "interaction_coefficients.csv", index=False)
    (path / "result_status.md").write_text("# CRE concentration interaction\n\nThe table reports a bank- and quarter-fixed-effects CRE-only regression. The interaction is the concentration effect on the unit CRE NCO rate; it is distinct from mechanical dollar exposure. Statistical interpretation requires the reported bank-clustered standard error and must not be replaced with significance hunting.\n", encoding="utf-8")
    return result
