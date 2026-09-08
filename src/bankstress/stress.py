"""Batch 4 Fed-scenario stress testing built from the approved Batch 1--3 panel.

This module deliberately produces a credit-loss / starting-Tier-1 result.  It
does not represent the result as a Federal Reserve CET1 projection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yaml
from matplotlib import pyplot as plt

from bankstress.macro import load_macro_config
from bankstress.modeling import _eligible_frame, _fit_entity_fe, _predict_entity_fe, load_model_specs
from bankstress.validation import fit_quantile, predict_quantile
from bankstress.artifacts import sha256_file, validate_artifact_metadata, write_artifact_metadata


OFFICIAL_SCENARIOS = ("baseline", "severely_adverse")
SCENARIO_MACRO_COLUMNS = {
    "gdp_growth": "gdp_growth",
    "unemployment_rate": "unemployment",
    "cre_price_growth": "cre_price_growth",
    "house_price_growth": "house_price_growth",
    "bbb_spread": "bbb_spread",
    "short_rate": "short_rate",
    "mortgage_rate": "mortgage_rate",
}

BANK_CONTROL_CURRENT_STATE = {
    "lagged_noncurrent_ratio": "npl_rate",
    "lagged_allowance_coverage": "allowance_coverage",
    "lagged_loan_growth": "loan_growth",
    "lagged_tier1_ratio": "tier1_ratio",
}

R4_RUN_ID = "r4-20260908-limited-delivery"
R4_FORMAL_PAIRS = {
    ("ar_mean", "CI"): "FORMAL_BASELINE",
    ("ar_mean", "CRE"): "FORMAL_BASELINE",
    ("dynamic_fe", "CI"): "LIMITED_CHALLENGER",
}


def load_stress_specs(root: Path) -> dict[str, Any]:
    with (root / "configs" / "stress_specs.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _quarter_end(values: pd.Series) -> pd.Series:
    # The Fed uses labels such as "2026 Q1", not ISO dates.
    return pd.PeriodIndex(values.str.replace(" ", "", regex=False), freq="Q").to_timestamp("Q")


def _download_csv(url: str, session: requests.sessions.Session | None = None) -> tuple[pd.DataFrame, bytes]:
    response = (session or requests.Session()).get(url, timeout=60)
    response.raise_for_status()
    content = response.content
    return pd.read_csv(StringIO(content.decode("utf-8-sig"))), content


def _annualized_to_qoq_percent(values: pd.Series) -> pd.Series:
    """Align Fed annualized real-GDP growth to the panel's simple QoQ percent."""
    return ((1 + pd.to_numeric(values, errors="raise") / 100) ** 0.25 - 1) * 100


def _historical_level_values(historic_levels: pd.DataFrame | pd.Series | None, level: str) -> pd.Series:
    """Return dated Fed index history used to bridge scenario transformations."""
    if historic_levels is None:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    if isinstance(historic_levels, pd.Series):
        # Backward-compatible support for a Q4 state supplied by small tests.
        if level not in historic_levels:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        return pd.Series([float(historic_levels[level])], index=[pd.Timestamp("2025-12-31")])
    required = {"quarter", level}
    if not required.issubset(historic_levels.columns):
        raise ValueError(f"Fed historical levels require columns {sorted(required)}")
    history = historic_levels[["quarter", level]].copy()
    history["quarter"] = pd.to_datetime(history["quarter"])
    history[level] = pd.to_numeric(history[level], errors="raise")
    return history.drop_duplicates("quarter", keep="last").set_index("quarter")[level].sort_index()


def _growth_from_levels(data: pd.DataFrame, level: str, periods: int, historic_levels: pd.DataFrame | pd.Series | None = None) -> pd.Series:
    """Calculate percent growth from Fed levels, seeding boundary quarters with history."""
    current = data.set_index("quarter")[level].astype(float)
    history = _historical_level_values(historic_levels, level)
    history = history[history.index < current.index.min()]
    combined = pd.concat([history, current]).sort_index()
    if combined.index.has_duplicates:
        raise ValueError(f"Duplicate Fed {level} level quarters")
    return current.div(combined.shift(periods).reindex(current.index)).sub(1).mul(100)


def _normalise_fed_frame(frame: pd.DataFrame, scenario: str, historic_levels: pd.DataFrame | pd.Series | None = None) -> pd.DataFrame:
    data = frame.copy()
    data["quarter"] = _quarter_end(data["Date"])
    data = data.sort_values("quarter").copy()
    data["scenario"] = scenario
    data["real_gdp_growth"] = pd.to_numeric(data["Real GDP growth"], errors="raise")
    data["gdp_growth"] = _annualized_to_qoq_percent(data["Real GDP growth"])
    data["unemployment"] = pd.to_numeric(data["Unemployment rate"], errors="raise")
    data["cre_price"] = pd.to_numeric(data["Commercial Real Estate Price Index (Level)"], errors="raise")
    data["house_price"] = pd.to_numeric(data["House Price Index (Level)"], errors="raise")
    data["bbb_yield"] = pd.to_numeric(data["BBB corporate yield"], errors="raise")
    data["short_rate"] = pd.to_numeric(data["3-month Treasury rate"], errors="raise")
    data["long_rate"] = pd.to_numeric(data["10-year Treasury yield"], errors="raise")
    data["mortgage_rate"] = pd.to_numeric(data["Mortgage rate"], errors="raise")
    # The Batch 2 named "bbb_spread" feature is FRED BAA10YM, a corporate-yield
    # spread over the 10-year Treasury.  The Fed publishes levels, so derive it.
    data["bbb_spread"] = data["bbb_yield"] - data["long_rate"]
    # Batch 2's CRE feature is FRED's already-reported YoY growth rate.  The
    # Fed publishes a CRE *level*, so derive the same YoY percent growth from
    # t-4.  Historical 2025 levels seed the first four 2026 scenario quarters.
    data["cre_price_growth"] = _growth_from_levels(data, "cre_price", 4, historic_levels).to_numpy()
    # House price remains the separately configured QoQ price-index feature.
    data["house_price_growth"] = _growth_from_levels(data, "house_price", 1, historic_levels).to_numpy()
    return data[["scenario", "quarter", "real_gdp_growth", "gdp_growth", "unemployment", "cre_price", "house_price", "bbb_yield", "mortgage_rate", "short_rate", "long_rate", "bbb_spread", "cre_price_growth", "house_price_growth"]]


def ingest_fed_2026_scenarios(root: Path, session: requests.sessions.Session | None = None) -> pd.DataFrame:
    """Re-fetch and validate the exact manifest-backed Fed 2026 inputs.

    The retained manifest is the input contract.  A newly downloaded byte
    stream is never silently substituted when its hash differs.
    """
    spec = load_stress_specs(root)["fed_2026"]
    manifest_path = root / "metadata" / "fed_2026_scenario_manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError("R4 requires metadata/fed_2026_scenario_manifest.csv")
    approved = pd.read_csv(manifest_path).set_index("artifact")
    required_artifacts = {"baseline", "severely_adverse", "historic_domestic"}
    if set(approved.index) != required_artifacts or approved.index.has_duplicates:
        raise ValueError("Fed scenario manifest must contain exactly the three approved artifacts")
    raw: dict[str, pd.DataFrame] = {}
    for name, key in (("baseline", "baseline_url"), ("severely_adverse", "severely_adverse_url"), ("historic_domestic", "historic_domestic_url")):
        if str(approved.loc[name, "source_url"]) != str(spec[key]):
            raise ValueError(f"Fed {name} URL differs from the retained manifest")
        frame, content = _download_csv(spec[key], session)
        observed_hash = _sha256(content)
        if observed_hash != str(approved.loc[name, "sha256"]):
            raise ValueError(f"Fed {name} bytes differ from the retained manifest hash")
        raw[name] = frame
    historic = raw["historic_domestic"].copy()
    historic["quarter"] = _quarter_end(historic["Date"])
    historic_levels = pd.DataFrame({
        "quarter": historic["quarter"],
        "cre_price": pd.to_numeric(historic["Commercial Real Estate Price Index (Level)"], errors="raise"),
        "house_price": pd.to_numeric(historic["House Price Index (Level)"], errors="raise"),
        "short_rate": pd.to_numeric(historic["3-month Treasury rate"], errors="raise"),
        "long_rate": pd.to_numeric(historic["10-year Treasury yield"], errors="raise"),
        "mortgage_rate": pd.to_numeric(historic["Mortgage rate"], errors="raise"),
    })
    scenario = pd.concat([_normalise_fed_frame(raw[name], name, historic_levels) for name in OFFICIAL_SCENARIOS], ignore_index=True)
    start, end = pd.Timestamp(spec["primary_start"]), pd.Timestamp(spec["primary_end"])
    scenario = scenario[scenario.quarter.between(start, end)].copy()
    scenario["horizon"] = scenario.groupby("scenario").cumcount() + 1
    scenario["scenario_type"] = "Fed official"
    external = root / "data" / "external"
    external.mkdir(parents=True, exist_ok=True)
    scenario.to_parquet(external / "fed_2026_scenarios.parquet", index=False)
    return scenario


def historic_macro_history(root: Path, session: requests.sessions.Session | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Return transformed Fed history used to seed the Batch 2 macro interface."""
    url = load_stress_specs(root)["fed_2026"]["historic_domestic_url"]
    historic, content = _download_csv(url, session)
    manifest = pd.read_csv(root / "metadata/fed_2026_scenario_manifest.csv").set_index("artifact")
    if url != manifest.loc["historic_domestic", "source_url"] or _sha256(content) != manifest.loc["historic_domestic", "sha256"]:
        raise ValueError("Fed historic boundary input does not match the retained manifest")
    historic["quarter"] = _quarter_end(historic["Date"])
    normalized = _normalise_fed_frame(historic.drop(columns="quarter"), "actual")
    required = {pd.Timestamp("2025-09-30"), pd.Timestamp("2025-12-31")}
    if not required.issubset(set(normalized["quarter"])):
        raise ValueError("Fed historic domestic data lacks the 2025Q3/Q4 macro state")
    levels = pd.DataFrame({
        "quarter": historic["quarter"],
        "cre_price": pd.to_numeric(historic["Commercial Real Estate Price Index (Level)"], errors="raise"),
        "house_price": pd.to_numeric(historic["House Price Index (Level)"], errors="raise"),
        "short_rate": pd.to_numeric(historic["3-month Treasury rate"], errors="raise"),
        "long_rate": pd.to_numeric(historic["10-year Treasury yield"], errors="raise"),
        "mortgage_rate": pd.to_numeric(historic["Mortgage rate"], errors="raise"),
    })
    return normalized, levels


def construct_stress_macro_predictors(scenarios: pd.DataFrame, actual_macro: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Apply the approved Batch 2 transformations and availability lags to Fed paths.

    `build_macro_panel` exposes GDP and unemployment as values available at a
    quarter-end origin, then `build_model_panel` lags them for the outcome.
    The final-vintage fallback series are shifted once in `build_macro_panel`
    and then once again in `build_model_panel`; therefore their future stress
    predictors use a two-quarter, rather than one-quarter, source delay.
    """
    definitions = load_macro_config(root)["series"]
    actual = actual_macro.set_index("quarter")
    rows: list[pd.DataFrame] = []
    for _, scenario in scenarios.groupby("scenario", sort=False):
        future = scenario.sort_values("quarter").reset_index(drop=True).copy()
        for definition in definitions.values():
            output_column = definition["output_column"]
            predictor = f"lagged_{output_column}"
            scenario_column = SCENARIO_MACRO_COLUMNS[output_column]
            # The model's own lag contributes one quarter.  Fallback final
            # values have already been shifted one additional quarter in the
            # leak-safe macro panel.
            source_delay = 1 if definition["availability"] == "vintage" else 2
            values: list[float] = []
            source_quarters: list[pd.Timestamp] = []
            for position, quarter in enumerate(future["quarter"]):
                source_position = position - source_delay
                if source_position >= 0:
                    source = future.iloc[source_position]
                    source_quarter = pd.Timestamp(source["quarter"])
                else:
                    source_quarter = pd.Period(quarter, freq="Q") - source_delay
                    source_quarter = source_quarter.to_timestamp("Q")
                    if source_quarter not in actual.index:
                        raise ValueError(f"Fed historic macro data lacks {source_quarter.date()} for {predictor}")
                    source = actual.loc[source_quarter]
                values.append(float(source[scenario_column]))
                source_quarters.append(source_quarter)
            future[predictor] = values
            future[f"{predictor}_source_quarter"] = source_quarters
        rows.append(future)
    return pd.concat(rows, ignore_index=True)


def make_sensitivity_scenarios(official: pd.DataFrame, historic_rates: pd.DataFrame | pd.Series, lambdas: list[float]) -> pd.DataFrame:
    """Create clearly-labelled researcher sensitivities from the fixed official paths."""
    baseline = official[official.scenario.eq("baseline")].sort_values("quarter").reset_index(drop=True)
    severe = official[official.scenario.eq("severely_adverse")].sort_values("quarter").reset_index(drop=True)
    if not baseline.quarter.equals(severe.quarter):
        raise ValueError("Official baseline and severely-adverse quarters do not align")
    numeric = [column for column in baseline if column not in {"scenario", "quarter", "horizon", "scenario_type", "cre_price_growth", "house_price_growth"}]
    rows: list[pd.DataFrame] = []
    for value in lambdas:
        item = baseline.copy()
        item[numeric] = baseline[numeric] + float(value) * (severe[numeric] - baseline[numeric])
        item["scenario"] = f"researcher_lambda_{value:g}"
        item["scenario_type"] = "Researcher sensitivity scenario"
        # Lambda is defined on the Fed-published scenario variables.  GDP is
        # published annualized, then transformed to this model's simple QoQ
        # feature only after interpolation.
        item["gdp_growth"] = _annualized_to_qoq_percent(item["real_gdp_growth"])
        item["bbb_spread"] = item["bbb_yield"] - item["long_rate"]
        item["cre_price_growth"] = _growth_from_levels(item, "cre_price", 4, historic_rates).to_numpy()
        item["house_price_growth"] = _growth_from_levels(item, "house_price", 1, historic_rates).to_numpy()
        rows.append(item)
    cre = baseline.copy()
    cre["cre_price"] = severe["cre_price"].to_numpy()
    cre["cre_price_growth"] = _growth_from_levels(cre, "cre_price", 4, historic_rates).to_numpy()
    cre["scenario"], cre["scenario_type"] = "researcher_cre_only", "Researcher partial-shock sensitivity"
    unemployment = baseline.copy()
    unemployment["unemployment"] = severe["unemployment"].to_numpy()
    unemployment["scenario"], unemployment["scenario_type"] = "researcher_unemployment_only", "Researcher partial-shock sensitivity"
    rates = baseline.copy()
    for column in ("short_rate", "long_rate", "mortgage_rate"):
        rates[column] = float(_historical_level_values(historic_rates, column).loc[_historical_level_values(historic_rates, column).index.max()])
    rates["bbb_spread"] = rates["bbb_yield"] - rates["long_rate"]
    rates["scenario"], rates["scenario_type"] = "researcher_high_for_longer_rates", "Researcher partial-shock sensitivity"
    return pd.concat([*rows, cre, unemployment, rates], ignore_index=True)


def _predictors_by_segment(eligible: pd.DataFrame, model_spec: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for segment in model_spec["primary_segments"]:
        subset = eligible[eligible.segment.eq(segment)]
        if not subset.empty:
            result[segment] = subset["sample_predictors"].iloc[0].split("|")
    return result


def stress_jump_off(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select only complete, eligible 2025Q4 bank-segment states; log exclusions."""
    spec, model_spec = load_stress_specs(root)["stress"], load_model_specs(root)
    date = pd.Timestamp(spec["jump_off"])
    candidates = panel[(pd.to_datetime(panel.report_date).eq(date)) & panel.segment.isin(spec["primary_segments"])].copy()
    required = ["nco_rate", "exposure", "tier1_capital", "allowance", "total_loans", "npl_rate", "allowance_coverage", "loan_growth", "tier1_ratio"]
    missing = candidates[required].isna().any(axis=1) | candidates["exposure"].le(0) | candidates["tier1_capital"].le(0)
    invalid = candidates["eligible_for_model"].ne(1) | candidates["merger_recent_flag"].ne(0) | missing
    exclusions = candidates.loc[invalid, ["bank_id", "bank_name", "segment"]].copy()
    exclusions["reason"] = np.select([
        candidates.loc[invalid, "eligible_for_model"].ne(1),
        candidates.loc[invalid, "merger_recent_flag"].ne(0),
        missing.loc[invalid],
    ], ["not eligible for approved model", "recent merger flag", "incomplete 2025Q4 jump-off state"], default="unknown")
    valid = candidates.loc[~invalid].copy()
    required_segments = set(spec["primary_segments"])
    complete_banks = set(valid.groupby(valid.bank_id.astype(str))["segment"].agg(set).loc[lambda sets: sets.eq(required_segments)].index)
    incomplete = valid[~valid.bank_id.astype(str).isin(complete_banks)][["bank_id", "bank_name", "segment"]].copy()
    incomplete["reason"] = "incomplete approved primary-segment portfolio at 2025Q4"
    exclusions = pd.concat([exclusions, incomplete], ignore_index=True)
    valid = valid[valid.bank_id.astype(str).isin(complete_banks)].copy()
    return valid, exclusions


@dataclass
class StressFit:
    name: str
    kind: str
    fit_by_segment: dict[str, Any]
    predictors: dict[str, list[str]]


def fit_stress_models(panel: pd.DataFrame, root: Path) -> list[StressFit]:
    model_spec = load_model_specs(root)
    eligible = _eligible_frame(panel, model_spec)
    predictors = _predictors_by_segment(eligible, model_spec)
    dynamic = {segment: _fit_entity_fe(eligible[eligible.segment.eq(segment)], "nco_rate", terms) for segment, terms in predictors.items()}
    quantile = {segment: fit_quantile(eligible[eligible.segment.eq(segment)], terms, 0.9, model_spec["quantile_spec"]) for segment, terms in predictors.items()}
    return [StressFit("dynamic_fe", "fe", dynamic, predictors), StressFit("quantile_0.9", "quantile", quantile, predictors)]


def _freeze_controls(jump_off: pd.DataFrame, current: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    state = current.copy()
    current_states = jump_off.copy()
    current_states["bank_id"] = current_states["bank_id"].astype(str)
    current_states = current_states.set_index("bank_id")
    for predictor in predictors:
        if predictor == "lagged_nco_rate":
            continue
        if predictor in BANK_CONTROL_CURRENT_STATE:
            state[predictor] = state["bank_id"].astype(str).map(current_states[BANK_CONTROL_CURRENT_STATE[predictor]])
    return state


def recursive_stress_paths(jump_off: pd.DataFrame, scenarios: pd.DataFrame, models: list[StressFit], loss_rate_floor: float = 0.0) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for scenario_name, scenario in scenarios.groupby("scenario", sort=True):
        for model in models:
            for segment, fit in model.fit_by_segment.items():
                origin = jump_off[jump_off.segment.eq(segment)].copy()
                if origin.empty:
                    continue
                states = origin.set_index(origin.bank_id.astype(str))["nco_rate"].to_dict()
                ordered_scenario = scenario.sort_values("quarter").reset_index(drop=True)
                for position, macro in enumerate(ordered_scenario.itertuples(index=False)):
                    current = origin.copy()
                    current["bank_id"] = current.bank_id.astype(str)
                    current["lagged_nco_rate"] = current.bank_id.map(states)
                    current["nco_rate"] = current["lagged_nco_rate"]  # required placeholder, never a future outcome
                    current = _freeze_controls(origin.assign(bank_id=origin.bank_id.astype(str)), current, model.predictors[segment])
                    for predictor in model.predictors[segment]:
                        if predictor in BANK_CONTROL_CURRENT_STATE or predictor == "lagged_nco_rate":
                            continue
                        if predictor in macro._fields:
                            current[predictor] = getattr(macro, predictor)
                    predicted = (_predict_entity_fe(fit, current, "nco_rate") if model.kind == "fe" else predict_quantile(fit, current))
                    if len(predicted) != len(origin):
                        raise ValueError(f"{model.name}/{segment} lost bank rows during recursive forecast")
                    raw_rate = predicted["prediction"].to_numpy(float)
                    aggregation_rate = np.maximum(raw_rate, float(loss_rate_floor))
                    # NCO is a net flow and can be negative.  The approved
                    # recursion therefore feeds the raw prediction forward;
                    # any non-negative loss floor affects dollar aggregation only.
                    states.update(dict(zip(predicted.bank_id.astype(str), raw_rate, strict=True)))
                    output = predicted[["bank_id", "bank_name", "segment", "exposure", "tier1_capital", "allowance", "total_loans"]].copy()
                    output["scenario"], output["scenario_type"], output["model"] = scenario_name, macro.scenario_type, model.name
                    output["quarter"], output["horizon"] = macro.quarter, macro.horizon
                    output["raw_predicted_nco_rate"] = raw_rate
                    output["predicted_nco_rate"] = raw_rate
                    output["loss_rate_for_aggregation"] = aggregation_rate
                    output["loss_rate_floor_applied"] = raw_rate < float(loss_rate_floor)
                    for predictor in model.predictors[segment]:
                        source_column = f"{predictor}_source_quarter"
                        if source_column in macro._fields:
                            output[source_column] = getattr(macro, source_column)
                    # The fitted outcome is an annualized NCO rate.  Convert it
                    # to its quarterly-dollar equivalent before aggregation.
                    output["predicted_loss"] = output["loss_rate_for_aggregation"] * output["exposure"] / 4
                    output.rename(columns={"tier1_capital": "starting_tier1", "allowance": "starting_allowance", "total_loans": "starting_loans"}, inplace=True)
                    pieces.append(output)
    return pd.concat(pieces, ignore_index=True)


def summarize_stress(paths: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bank = (paths.groupby(["bank_id", "bank_name", "scenario", "scenario_type", "model"], as_index=False)
            .agg(cumulative_loss=("predicted_loss", "sum"), starting_tier1=("starting_tier1", "first"), starting_allowance=("starting_allowance", "first"), starting_loans=("starting_loans", "first")))
    segment = (paths.groupby(["bank_id", "bank_name", "scenario", "scenario_type", "model", "segment"], as_index=False)
               .agg(segment_loss=("predicted_loss", "sum")))
    pivot = segment.pivot(index=["bank_id", "bank_name", "scenario", "scenario_type", "model"], columns="segment", values="segment_loss").fillna(0).reset_index()
    for name in ("CRE", "CI"):
        if name not in pivot:
            pivot[name] = 0.0
    summary = bank.merge(pivot, on=["bank_id", "bank_name", "scenario", "scenario_type", "model"], validate="one_to_one")
    summary["capital_depletion"] = summary.cumulative_loss / summary.starting_tier1
    summary["loss_to_loans"] = summary.cumulative_loss / summary.starting_loans
    summary["allowance_adjusted_loss"] = (summary.cumulative_loss - summary.starting_allowance).clip(lower=0)
    return summary, segment


def cre_group_table(summary: pd.DataFrame, jump_off: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    exposure = jump_off[jump_off.segment.eq("CRE")][["bank_id", "cre_to_tier1", "cre_share"]].drop_duplicates("bank_id").copy()
    exposure["cre_group"] = pd.qcut(exposure["cre_to_tier1"].rank(method="first"), q=3, labels=["Low", "Mid", "High"])
    detail = summary.merge(exposure[["bank_id", "cre_to_tier1", "cre_share", "cre_group"]], on="bank_id", how="inner", validate="many_to_one")
    focus = detail[(detail.scenario.eq("severely_adverse")) & detail.model.eq("dynamic_fe")]
    groups = focus.groupby("cre_group", observed=True).agg(n_banks=("bank_id", "nunique"), mean_severe_loss=("cumulative_loss", "mean"), mean_capital_depletion=("capital_depletion", "mean"), median_capital_depletion=("capital_depletion", "median"), mean_allowance_adjusted_loss=("allowance_adjusted_loss", "mean"), mean_cre_contribution=("CRE", "mean")).reset_index()
    high = groups.loc[groups.cre_group.eq("High"), "mean_capital_depletion"]
    low = groups.loc[groups.cre_group.eq("Low"), "mean_capital_depletion"]
    groups["difference_high_low_capital_depletion"] = float(high.iloc[0] - low.iloc[0]) if len(high) and len(low) else np.nan
    return detail, groups


def ranking_stability(summary: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    severe = summary[summary.scenario.eq("severely_adverse")].copy()
    models = sorted(severe.model.unique())
    rows: list[dict[str, Any]] = []
    for left_index, left in enumerate(models):
        for right in models[left_index + 1:]:
            a = severe[severe.model.eq(left)].set_index("bank_id")["capital_depletion"]
            b = severe[severe.model.eq(right)].set_index("bank_id")["capital_depletion"]
            aligned = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
            n_top = max(1, int(np.ceil(len(aligned) / 4)))
            top_a = set(aligned.nlargest(n_top, "a").index)
            top_b = set(aligned.nlargest(n_top, "b").index)
            rows.append({"scenario": "severely_adverse", "left_model": left, "right_model": right, "n_banks": len(aligned), "spearman_rank_correlation": aligned.a.rank().corr(aligned.b.rank(), method="pearson"), "top_quartile_n": n_top, "top_quartile_overlap": len(top_a & top_b) / n_top})
    diagnostics = pd.read_csv(root / "outputs" / "models" / "bayesian" / "diagnostics.csv")
    availability = pd.DataFrame([
        {"model": "dynamic_fe", "status": "included", "reason": "approved mean model"},
        {"model": "quantile_0.9", "status": "included_with_limitation", "reason": "pre-specified downstream tail model; Batch 3 records inadequate recursive tail calibration"},
        {"model": "bayesian", "status": "unavailable", "reason": "; ".join(diagnostics.get("reason", pd.Series(dtype=str)).dropna().astype(str).unique()) or "Batch 3 had no usable posterior forecasts"},
    ])
    return pd.DataFrame(rows), availability


def write_stress_figures(paths: pd.DataFrame, summary: pd.DataFrame, cre_detail: pd.DataFrame, groups: pd.DataFrame, root: Path) -> None:
    directory = root / "outputs" / "stress" / "figures"
    directory.mkdir(parents=True, exist_ok=True)
    primary = paths[paths.model.eq("dynamic_fe")]
    fig, ax = plt.subplots(figsize=(9, 5))
    for scenario in OFFICIAL_SCENARIOS:
        data = primary[primary.scenario.eq(scenario)].groupby("quarter").predicted_loss.sum()
        ax.plot(data.index, data.cumsum(), label=scenario)
    ax.set(title="System cumulative credit loss: baseline vs severely adverse", ylabel="Cumulative loss (thousands)", xlabel="Quarter"); ax.legend(); fig.tight_layout(); fig.savefig(directory / "baseline_vs_severe_system_loss.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 5)); primary[primary.scenario.eq("severely_adverse")].groupby("segment").predicted_loss.sum().plot.bar(ax=ax); ax.set(title="Severely adverse loss by segment", ylabel="Cumulative loss (thousands)"); fig.tight_layout(); fig.savefig(directory / "segment_contribution.png", dpi=150); plt.close(fig)
    focus = cre_detail[(cre_detail.scenario.eq("severely_adverse")) & cre_detail.model.eq("dynamic_fe")]
    fig, ax = plt.subplots(figsize=(7, 5)); ax.scatter(focus.cre_to_tier1, focus.capital_depletion); ax.set(title="CRE-to-Tier1 and capital depletion", xlabel="CRE-to-Tier1", ylabel="Credit loss / starting Tier1"); fig.tight_layout(); fig.savefig(directory / "cre_to_capital_vs_depletion.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 5)); groups.set_index("cre_group").mean_capital_depletion.plot.bar(ax=ax); ax.set(title="Capital depletion by CRE group", ylabel="Credit loss / starting Tier1"); fig.tight_layout(); fig.savefig(directory / "cre_groups_capital_depletion.png", dpi=150); plt.close(fig)
    sensitivity = summary[(summary.model.eq("dynamic_fe")) & summary.scenario.str.startswith("researcher_lambda_")].groupby("scenario").cumulative_loss.sum()
    fig, ax = plt.subplots(figsize=(7, 5)); sensitivity.plot.bar(ax=ax); ax.set(title="Researcher lambda sensitivity", ylabel="Cumulative loss (thousands)"); fig.tight_layout(); fig.savefig(directory / "lambda_sensitivity.png", dpi=150); plt.close(fig)
    rankings = summary[summary.scenario.eq("severely_adverse")].pivot(index="bank_name", columns="model", values="capital_depletion")
    fig, ax = plt.subplots(figsize=(7, 5)); rankings.rank(ascending=False).plot.scatter(x="dynamic_fe", y="quantile_0.9", ax=ax); ax.set(title="Model stress-rank comparison", xlabel="Dynamic FE rank", ylabel="Q0.90 rank"); fig.tight_layout(); fig.savefig(directory / "model_ranking_stability.png", dpi=150); plt.close(fig)


def floor_use_qa(paths: pd.DataFrame) -> pd.DataFrame:
    """Report the aggregation-only non-negative-floor use by stress path."""
    return (paths.groupby(["scenario", "scenario_type", "model", "segment"], as_index=False)
            .agg(floor_use_count=("loss_rate_floor_applied", "sum"),
                 path_observations=("loss_rate_floor_applied", "size"),
                 raw_predicted_nco_min=("raw_predicted_nco_rate", "min"),
                 aggregated_loss=("predicted_loss", "sum")))


def committed_mean_model_oos_comparison(root: Path) -> tuple[pd.DataFrame, str, float]:
    """Select the best mean model from committed AR and Dynamic-FE OOS evidence."""
    paths = {
        "ar": root / "outputs" / "models" / "ar" / "oos_metrics.csv",
        "dynamic_fe": root / "outputs" / "models" / "dynamic_fe" / "oos_metrics.csv",
    }
    frames = []
    for model, path in paths.items():
        frame = pd.read_csv(path)
        if frame.empty or not {"n", "rmse"}.issubset(frame.columns):
            raise ValueError(f"Committed OOS metrics are incomplete for {model}")
        frames.append(frame.assign(model=model))
    metrics = pd.concat(frames, ignore_index=True)
    comparison = (metrics.groupby("model", as_index=False)
                  .apply(lambda group: pd.Series({
                      "oos_observations": int(group["n"].sum()),
                      "pooled_oos_rmse": float(np.sqrt(np.average(group["rmse"].pow(2), weights=group["n"]))),
                  }), include_groups=False)
                  .reset_index(drop=True))
    ar_rmse = float(comparison.loc[comparison.model.eq("ar"), "pooled_oos_rmse"].iloc[0])
    comparison["rmse_improvement_vs_ar"] = (ar_rmse - comparison["pooled_oos_rmse"]) / ar_rmse
    best = comparison.sort_values(["pooled_oos_rmse", "model"], kind="stable").iloc[0]
    return comparison, str(best["model"]), float(best["rmse_improvement_vs_ar"])


def _run_stress_legacy(root: Path, session: requests.sessions.Session | None = None) -> dict[str, Any]:
    panel_path = root / "data" / "derived" / "model_panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError("Batch 4 requires the real Batch 1--3 model panel")
    panel = pd.read_parquet(panel_path)
    official = ingest_fed_2026_scenarios(root, session)
    actual_macro, historic_rates = historic_macro_history(root, session)
    stress_spec = load_stress_specs(root)["stress"]
    all_scenarios = pd.concat([official, make_sensitivity_scenarios(official, historic_rates, stress_spec["lambdas"])], ignore_index=True)
    all_scenarios = construct_stress_macro_predictors(all_scenarios, actual_macro, root)
    jump, exclusions = stress_jump_off(panel, root)
    models = fit_stress_models(panel, root)
    paths = recursive_stress_paths(jump, all_scenarios, models, float(stress_spec["loss_rate_floor"]))
    summaries, segments = summarize_stress(paths)
    detail, groups = cre_group_table(summaries, jump)
    stability, availability = ranking_stability(summaries, root)
    stress_dir, report_dir = root / "outputs" / "stress", root / "outputs" / "reporting"
    stress_dir.mkdir(parents=True, exist_ok=True); report_dir.mkdir(parents=True, exist_ok=True)
    paths.to_parquet(stress_dir / "stress_paths.parquet", index=False)
    floor_qa = floor_use_qa(paths)
    floor_qa.to_csv(stress_dir / "loss_rate_floor_qa.csv", index=False)
    timing_columns = ["scenario", "scenario_type", "quarter", "horizon", *[column for column in all_scenarios if column.endswith("_source_quarter")]]
    all_scenarios[timing_columns].to_csv(stress_dir / "macro_predictor_timing.csv", index=False)
    # T4 is one row per bank/model.  Its loss attribution and capital fields are
    # deliberately the official severely-adverse result, while baseline loss is
    # retained alongside it for the required comparison.
    official_summary = summaries[summaries.scenario.isin(OFFICIAL_SCENARIOS)].copy()
    baseline_loss = (official_summary[official_summary.scenario.eq("baseline")]
                     [["bank_id", "bank_name", "model", "cumulative_loss"]]
                     .rename(columns={"cumulative_loss": "baseline_loss"}))
    t4 = (official_summary[official_summary.scenario.eq("severely_adverse")]
          [["bank_id", "bank_name", "model", "cumulative_loss", "CRE", "CI", "capital_depletion", "allowance_adjusted_loss", "loss_to_loans"]]
          .rename(columns={"cumulative_loss": "severe_loss", "CRE": "cre_loss", "CI": "ci_loss"})
          .merge(baseline_loss, on=["bank_id", "bank_name", "model"], validate="one_to_one"))
    t4["mortgage_loss"] = np.nan
    t4["mortgage_loss_status"] = "unavailable: approved stress models cover CRE and CI only"
    t4 = t4[["bank_id", "bank_name", "model", "baseline_loss", "severe_loss", "cre_loss", "ci_loss", "mortgage_loss", "mortgage_loss_status", "capital_depletion", "allowance_adjusted_loss", "loss_to_loans"]]
    t4.to_csv(stress_dir / "t4_fed_stress_results.csv", index=False)
    pd.DataFrame([{"segment": "CRE", "status": "included"}, {"segment": "CI", "status": "included"}, {"segment": "Mortgage", "status": "unavailable: no approved Batch 1--3 mortgage stress model"}]).to_csv(stress_dir / "segment_attribution_status.csv", index=False)
    sensitivity_rows = []
    for (scenario, model), group in summaries.groupby(["scenario", "model"]):
        sensitivity_rows.append({"sensitivity": scenario, "model": model, "aggregate_cumulative_loss": group.cumulative_loss.sum(), "mean_capital_depletion": group.capital_depletion.mean()})
    for change in stress_spec["exposure_sensitivities"]:
        base = summaries[(summaries.scenario.eq("severely_adverse")) & summaries.model.eq("dynamic_fe")]
        sensitivity_rows.append({"sensitivity": f"exposure_{change:+.0%}", "model": "dynamic_fe", "aggregate_cumulative_loss": base.cumulative_loss.sum() * (1 + change), "mean_capital_depletion": base.capital_depletion.mean() * (1 + change)})
    pd.DataFrame(sensitivity_rows).to_csv(stress_dir / "t5_sensitivity.csv", index=False)
    groups.to_csv(stress_dir / "cre_group_table.csv", index=False); detail.to_csv(stress_dir / "cre_group_detail.csv", index=False)
    exclusions.to_csv(stress_dir / "stress_universe_exclusions.csv", index=False); stability.to_csv(stress_dir / "ranking_stability.csv", index=False); availability.to_csv(stress_dir / "model_availability.csv", index=False)
    monotonic = summaries[summaries.model.eq("dynamic_fe")].groupby("scenario").cumulative_loss.sum()
    monotonic_rows = []
    ordered = [("baseline", monotonic.get("baseline", np.nan)), ("lambda_0.5", monotonic.get("researcher_lambda_0.5", np.nan)), ("lambda_1.0", monotonic.get("researcher_lambda_1", np.nan)), ("lambda_1.25", monotonic.get("researcher_lambda_1.25", np.nan))]
    for (name, value), (_, prior) in zip(ordered[1:], ordered[:-1], strict=True): monotonic_rows.append({"comparison": name, "aggregate_loss": value, "nondecreasing_vs_prior": bool(value >= prior)})
    pd.DataFrame(monotonic_rows).to_csv(stress_dir / "severity_monotonicity_qa.csv", index=False)
    primary = summaries[(summaries.scenario.eq("severely_adverse")) & summaries.model.eq("dynamic_fe")]
    high_low = float(groups["difference_high_low_capital_depletion"].dropna().iloc[0]) if groups["difference_high_low_capital_depletion"].notna().any() else None
    reconciliation = pd.read_csv(root / "outputs" / "qa" / "reconciliation_summary.csv")
    evaluable = reconciliation[~reconciliation["nco_reconciliation_status"].eq("NOT_EVALUABLE_MISSING_FLOW")]
    reconciliation_rate = float(evaluable["nco_reconciliation_status"].str.startswith(("PASS", "EXPLAINED")).mean()) if not evaluable.empty else np.nan
    mean_model_comparison, best_model_name, best_improvement = committed_mean_model_oos_comparison(root)
    mean_model_comparison.to_csv(stress_dir / "mean_model_oos_comparison.csv", index=False)
    mapping = pd.read_csv(root / "metadata" / "field_mapping.csv")
    metrics = {"n_banks": int(jump.bank_id.nunique()), "n_observations": int(len(panel)), "n_raw_fields": int(mapping["raw_code"].nunique()), "reconciliation_rate": reconciliation_rate, "best_oos_rmse_improvement_vs_ar": best_improvement, "best_model_name": best_model_name, "high_cre_capital_depletion_difference": high_low, "high_cre_group_definition": "2025Q4 CRE-to-Tier1 terciles among the final stress universe", "stress_scenario": "Fed 2026 severely adverse"}
    import json
    (report_dir / "resume_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    write_stress_figures(paths, summaries, detail, groups, root)
    (stress_dir / "run_summary.md").write_text("# Batch 4 Fed stress results\n\n"
        f"- Final stress universe: {metrics['n_banks']} banks, each with complete CRE and C&I 2025Q4 states.\n"
        "- Official scenarios are the Federal Reserve's 2026 final baseline and severely adverse domestic CSVs; lambda and partial shocks are clearly labelled researcher sensitivities.\n"
        "- Primary capital result is cumulative credit loss / starting Tier 1 capital, not a Federal Reserve CET1 projection. Annualized NCO rates are divided by four; the non-negative floor applies only to dollar-loss aggregation and not to the recursive NCO state.\n"
        "- Reviewer-mandated CRE definition correction: the historical FRED input is its reported YoY CRE-price growth, and Fed CRE index levels are transformed to the same YoY percent-growth units using historical boundary levels.\n"
        "- 2026Q1 bank controls use the actual 2025Q4 current state and remain static. GDP/unemployment scenario features first affect 2026Q2, while final-vintage fallback features first affect 2026Q3 because Batch 2 applies their documented availability lag and the model then applies its own lag; `macro_predictor_timing.csv` records all sources.\n"
        f"- Dollar-loss floor use: {int(floor_qa.floor_use_count.sum())} of {int(floor_qa.path_observations.sum())} path observations; see `loss_rate_floor_qa.csv`. Mortgage attribution is unavailable, not zero-filled, because no approved mortgage stress model exists.\n"
        "- Bayesian ranking is unavailable because Batch 3 recorded no usable posterior forecasts; it is not imputed.\n", encoding="utf-8")
    return {"paths": paths, "summary": summaries, "groups": groups, "stability": stability, "metrics": metrics}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_formal_r4_inputs(
    root: Path,
    *,
    additional_formal_artifacts: list[Path] | None = None,
) -> dict[str, Any]:
    """Fail closed unless every formal R1--R3 dependency is current.

    Residual-calibration artifacts are deliberately not part of limited R4.
    Supplying one to the formal entry point is therefore an error, even when a
    legacy file remains on disk for audit purposes.
    """
    if additional_formal_artifacts:
        names = ", ".join(path.relative_to(root).as_posix() for path in additional_formal_artifacts)
        raise ValueError(f"Limited R4 does not authorize residual/extra formal inputs: {names}")

    artifacts = {
        "credit_panel": (root / "data/derived/credit_panel.parquet", "R1"),
        "model_panel": (root / "data/derived/model_panel.parquet", "R2"),
        "r2_summary": (root / "outputs/repair/r2/validation_summary.json", "R2"),
        "dynamic_coefficients": (root / "outputs/models/dynamic_fe/coefficients.csv", "R2"),
        "ar_metrics": (root / "outputs/models/ar/oos_metrics.csv", "R2"),
        "registry": (root / "outputs/validation/model_use_registry.json", "R3"),
        "r3_summary": (root / "outputs/repair/r3/validation_summary.json", "R3"),
    }
    metadata: dict[str, dict[str, Any]] = {}
    for name, (path, stage) in artifacts.items():
        metadata[name] = validate_artifact_metadata(path, expected_stage=stage)

    r1 = _read_json(root / "outputs/repair/r1/validation_summary.json")
    r2 = _read_json(artifacts["r2_summary"][0])
    r3 = _read_json(artifacts["r3_summary"][0])
    registry = _read_json(artifacts["registry"][0])
    model_panel_hash = sha256_file(artifacts["model_panel"][0])
    field_mapping_hash = sha256_file(root / "metadata/field_mapping.csv")
    raw_manifest_hash = sha256_file(root / "data/manifests/ffiec_manifest.csv")
    model_spec_hash = sha256_file(root / "configs/model_specs.yaml")

    failures: list[str] = []
    if r1.get("validation_status") != "PASS" or r2.get("validation_status") != "PASS" or r3.get("validation_status") != "PASS":
        failures.append("an upstream repair validation summary is not PASS")
    if r2.get("input_run_id") != r1.get("run_id"):
        failures.append("R2 input run does not match R1")
    if r3.get("input_run_id") != r2.get("run_id"):
        failures.append("R3 input run does not match R2")
    if r3.get("input_model_panel_hash") != model_panel_hash:
        failures.append("R3 model-panel hash does not match the current R2 panel")
    if any(item.get("input_run_id") != r2.get("run_id") for item in registry):
        failures.append("model-use registry contains a stale R2 input run")
    if any(item.get("model_spec_hash") != model_spec_hash for item in registry):
        failures.append("model-use registry contains a stale model specification")
    for name, payload in metadata.items():
        if payload.get("field_mapping_hash") != field_mapping_hash:
            failures.append(f"{name} carries a stale field mapping hash")
        if payload.get("raw_manifest_hash") != raw_manifest_hash:
            failures.append(f"{name} carries a stale raw-manifest hash")
        if payload.get("model_spec_hash") not in (None, model_spec_hash):
            failures.append(f"{name} carries a stale model specification hash")
    for name in ("dynamic_coefficients", "ar_metrics", "registry"):
        recorded = metadata[name].get("input_artifact_hashes", {}).get("data/derived/model_panel.parquet")
        if recorded != model_panel_hash:
            failures.append(f"{name} does not depend on the current model panel")

    registry_map = {(item["model_id"], item["segment"]): item for item in registry}
    for pair in R4_FORMAL_PAIRS:
        if registry_map.get(pair, {}).get("conditional_mean_stress_use") != "ALLOWED":
            failures.append(f"registry does not authorize {pair[0]}/{pair[1]}")
    forbidden = [
        pair for pair, item in registry_map.items()
        if item.get("conditional_mean_stress_use") != "ALLOWED" and pair in R4_FORMAL_PAIRS
    ]
    if forbidden:
        failures.append(f"forbidden model pairs entered the formal universe: {forbidden}")
    if failures:
        raise ValueError("Formal R4 lineage gate failed: " + "; ".join(dict.fromkeys(failures)))
    return {
        "r1_run_id": r1["run_id"],
        "r2_run_id": r2["run_id"],
        "r3_run_id": r3["run_id"],
        "model_panel_hash": model_panel_hash,
        "field_mapping_hash": field_mapping_hash,
        "raw_manifest_hash": raw_manifest_hash,
        "model_spec_hash": model_spec_hash,
        "registry_hash": sha256_file(artifacts["registry"][0]),
        "registry": registry,
    }


def _r4_jump_off(panel: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the common C&I/CRE 2025Q4 universe without filling gaps."""
    date = pd.Timestamp(load_stress_specs(root)["stress"]["jump_off"])
    candidates = panel.loc[
        pd.to_datetime(panel["report_date"]).eq(date) & panel["segment"].isin(["CI", "CRE"])
    ].copy()
    required = [
        "nco_rate", "exposure", "tier1_capital", "allowance", "total_loans",
        "npl_rate", "allowance_coverage", "loan_growth", "tier1_ratio",
    ]
    candidates["bank_id"] = candidates["bank_id"].astype(str)
    candidates["base_valid"] = (
        candidates["eligible_for_model"].eq(1)
        & candidates["merger_recent_flag"].eq(0)
        & candidates[required].notna().all(axis=1)
        & candidates["exposure"].gt(0)
        & candidates["tier1_capital"].gt(0)
    )
    valid_sets = candidates.loc[candidates["base_valid"]].groupby("bank_id")["segment"].agg(set)
    complete_banks = set(valid_sets.loc[valid_sets.eq({"CI", "CRE"})].index)
    valid = candidates.loc[candidates["bank_id"].isin(complete_banks)].copy()
    excluded = candidates.loc[~candidates["bank_id"].isin(complete_banks), ["bank_id", "bank_name", "segment", "base_valid"]].copy()
    excluded["reason"] = np.where(
        excluded["base_valid"],
        "other primary segment lacks a valid 2025Q4 jump-off",
        "segment lacks eligible complete 2025Q4 state",
    )
    return valid.drop(columns="base_valid"), excluded.drop(columns="base_valid")


def fit_r4_models(panel: pd.DataFrame, root: Path) -> list[StressFit]:
    """Fit only the three registry-authorized conditional-mean pairs."""
    spec = load_model_specs(root)
    eligible = _eligible_frame(panel, spec)
    fits: list[StressFit] = []
    ar_by_segment: dict[str, Any] = {}
    ar_predictors: dict[str, list[str]] = {}
    for segment in ("CI", "CRE"):
        train = eligible.loc[eligible["segment"].eq(segment) & eligible["evaluation_eligible"]]
        ar_by_segment[segment] = _fit_entity_fe(train, "nco_rate", ["lagged_nco_rate"])
        ar_predictors[segment] = ["lagged_nco_rate"]
    fits.append(StressFit("ar_mean", "fe", ar_by_segment, ar_predictors))

    ci = eligible.loc[eligible["segment"].eq("CI") & eligible["evaluation_eligible"]]
    ci_predictors = ci["sample_predictors"].iloc[0].split("|")
    fits.append(StressFit(
        "dynamic_fe", "fe", {"CI": _fit_entity_fe(ci, "nco_rate", ci_predictors)}, {"CI": ci_predictors}
    ))
    return fits


def recursive_r4_paths(
    jump_off: pd.DataFrame,
    scenarios: pd.DataFrame,
    models: list[StressFit],
    *,
    loss_rate_floor: float = 0.0,
) -> pd.DataFrame:
    """Generate authorized paths with quarterly state and input lineage."""
    pieces: list[pd.DataFrame] = []
    jump_date = pd.Timestamp("2025-12-31")
    for scenario_name, scenario in scenarios.groupby("scenario", sort=True):
        ordered = scenario.sort_values("quarter").reset_index(drop=True)
        for model in models:
            for segment, fit in model.fit_by_segment.items():
                pair = (model.name, segment)
                if pair not in R4_FORMAL_PAIRS:
                    raise ValueError(f"Unauthorized formal stress pair: {model.name}/{segment}")
                origin = jump_off.loc[jump_off["segment"].eq(segment)].copy()
                origin["bank_id"] = origin["bank_id"].astype(str)
                states = origin.set_index("bank_id")["nco_rate"].to_dict()
                state_quarters = {bank: jump_date for bank in states}
                state_types = {bank: "ACTUAL_2025Q4_JUMP_OFF" for bank in states}
                for macro in ordered.itertuples(index=False):
                    current = origin.copy()
                    current["lagged_nco_rate"] = current["bank_id"].map(states)
                    current["nco_rate"] = current["lagged_nco_rate"]
                    current = _freeze_controls(origin, current, model.predictors[segment])
                    for predictor in model.predictors[segment]:
                        if predictor in BANK_CONTROL_CURRENT_STATE or predictor == "lagged_nco_rate":
                            continue
                        if predictor not in macro._fields:
                            raise ValueError(f"Scenario lacks required predictor {predictor}")
                        current[predictor] = getattr(macro, predictor)
                    predicted = _predict_entity_fe(fit, current, "nco_rate")
                    if len(predicted) != len(origin):
                        raise ValueError(f"{model.name}/{segment} lost banks in recursion")
                    raw_rate = predicted["prediction"].to_numpy(float)
                    aggregation_rate = np.maximum(raw_rate, float(loss_rate_floor))
                    output = predicted[["bank_id", "bank_name", "segment", "exposure", "tier1_capital", "allowance", "total_loans"]].copy()
                    output["scenario"] = scenario_name
                    output["scenario_type"] = macro.scenario_type
                    output["model"] = model.name
                    output["formal_use"] = R4_FORMAL_PAIRS[pair]
                    output["quarter"] = macro.quarter
                    output["horizon"] = macro.horizon
                    output["input_lagged_nco_rate"] = output["bank_id"].map(states)
                    output["lagged_nco_rate_source_quarter"] = output["bank_id"].map(state_quarters)
                    output["lagged_nco_rate_source_type"] = output["bank_id"].map(state_types)
                    for predictor in model.predictors[segment]:
                        output[f"input_{predictor}"] = predicted[predictor].to_numpy()
                        if predictor in BANK_CONTROL_CURRENT_STATE:
                            output[f"{predictor}_source_quarter"] = jump_date
                            output[f"{predictor}_source_type"] = "ACTUAL_2025Q4_FROZEN_CONTROL"
                        elif predictor != "lagged_nco_rate":
                            output[f"{predictor}_source_quarter"] = getattr(macro, f"{predictor}_source_quarter")
                            output[f"{predictor}_source_type"] = getattr(macro, f"{predictor}_source_type")
                    output["raw_predicted_nco_rate_decimal_annualized"] = raw_rate
                    output["loss_rate_for_aggregation_decimal_annualized"] = aggregation_rate
                    output["loss_rate_floor_applied"] = raw_rate < float(loss_rate_floor)
                    output["quarter_loss_thousands"] = aggregation_rate / 4.0 * output["exposure"]
                    output["quarter_loss_thousands_unfloored"] = raw_rate / 4.0 * output["exposure"]
                    output["exposure_source_quarter"] = jump_date
                    output["exposure_assumption"] = "STATIC_2025Q4_EXPOSURE_THOUSANDS"
                    output.rename(columns={
                        "tier1_capital": "starting_tier1_thousands",
                        "allowance": "starting_allowance_thousands",
                        "total_loans": "starting_loans_thousands",
                        "exposure": "exposure_thousands",
                    }, inplace=True)
                    pieces.append(output)
                    states.update(dict(zip(predicted["bank_id"].astype(str), raw_rate, strict=True)))
                    state_quarters.update({bank: pd.Timestamp(macro.quarter) for bank in predicted["bank_id"].astype(str)})
                    state_types.update({bank: "MODELED_RECURSIVE_CONDITIONAL_MEAN" for bank in predicted["bank_id"].astype(str)})
    result = pd.concat(pieces, ignore_index=True)
    if set(zip(result["model"], result["segment"])) != set(R4_FORMAL_PAIRS):
        raise AssertionError("Formal path universe differs from the authorized registry scope")
    return result


def _summarize_r4(paths: pd.DataFrame) -> pd.DataFrame:
    return (paths.groupby(["bank_id", "bank_name", "scenario", "scenario_type", "model", "formal_use", "segment"], as_index=False)
            .agg(cumulative_loss_thousands=("quarter_loss_thousands", "sum"),
                 cumulative_loss_thousands_unfloored=("quarter_loss_thousands_unfloored", "sum"),
                 starting_tier1_thousands=("starting_tier1_thousands", "first"),
                 exposure_thousands=("exposure_thousands", "first"))
            .assign(modeled_credit_loss_burden=lambda x: x.cumulative_loss_thousands / x.starting_tier1_thousands,
                    modeled_credit_loss_burden_unfloored=lambda x: x.cumulative_loss_thousands_unfloored / x.starting_tier1_thousands))


def _cre_group_outputs(summary: pd.DataFrame, jump: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    exposure = jump.loc[jump["segment"].eq("CRE"), ["bank_id", "bank_name", "cre_to_tier1", "cre_share", "exposure", "tier1_capital"]].copy()
    exposure["bank_id"] = exposure["bank_id"].astype(str)
    exposure["cre_group"] = pd.qcut(exposure["cre_to_tier1"].rank(method="first"), 3, labels=["Low", "Mid", "High"])
    severe = summary.loc[
        summary["scenario"].eq("severely_adverse") & summary["model"].eq("ar_mean") & summary["segment"].eq("CRE")
    ].copy()
    detail = exposure.merge(severe[["bank_id", "cumulative_loss_thousands", "modeled_credit_loss_burden"]], on="bank_id", validate="one_to_one")
    reference_rate = float(detail["cumulative_loss_thousands"].sum() / detail["exposure"].sum())
    detail["equal_loss_rate_reference"] = reference_rate
    detail["mechanical_equal_rate_loss_thousands"] = detail["exposure"] * reference_rate
    detail["mechanical_equal_rate_burden"] = detail["mechanical_equal_rate_loss_thousands"] / detail["tier1_capital"]
    detail["decomposition_status"] = "DESCRIPTIVE_NOT_CAUSAL"
    groups = (detail.groupby("cre_group", observed=True, as_index=False)
              .agg(n_banks=("bank_id", "nunique"),
                   cre_to_tier1_min=("cre_to_tier1", "min"), cre_to_tier1_max=("cre_to_tier1", "max"),
                   mean_modeled_cre_burden=("modeled_credit_loss_burden", "mean"),
                   mean_mechanical_equal_rate_burden=("mechanical_equal_rate_burden", "mean"),
                   mean_modeled_cre_loss_thousands=("cumulative_loss_thousands", "mean")))
    groups["equal_loss_rate_reference"] = reference_rate
    groups["interpretation"] = "Exposure/Tier1 decomposition only; no causal concentration effect"
    return detail, groups


def _write_r4_figures(paths: pd.DataFrame, cre_detail: pd.DataFrame, root: Path) -> list[Path]:
    directory = root / "outputs/stress/figures"
    directory.mkdir(parents=True, exist_ok=True)
    ar = paths.loc[paths["model"].eq("ar_mean")]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for scenario in OFFICIAL_SCENARIOS:
        series = ar.loc[ar["scenario"].eq(scenario)].groupby("quarter")["quarter_loss_thousands"].sum().cumsum()
        ax.plot(series.index, series, label=scenario)
    ax.set(title="AR conditional-mean cumulative credit-loss burden", xlabel="Quarter", ylabel="Loss (thousands)")
    ax.legend(); fig.tight_layout(); path1 = directory / "baseline_vs_severe_system_loss.png"; fig.savefig(path1, dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4.8))
    ax.scatter(cre_detail["cre_to_tier1"], cre_detail["modeled_credit_loss_burden"])
    ax.set(title="CRE exposure and modeled CRE loss burden", xlabel="2025Q4 CRE / Tier1", ylabel="CRE loss / starting Tier1")
    fig.tight_layout(); path2 = directory / "cre_to_tier1_vs_modeled_burden.png"; fig.savefig(path2, dpi=150); plt.close(fig)
    return [path1, path2]


def _write_r4_sidecars(root: Path, paths: list[Path], gate: dict[str, Any]) -> None:
    inputs = [
        root / "data/derived/model_panel.parquet",
        root / "outputs/validation/model_use_registry.json",
        root / "outputs/repair/r2/validation_summary.json",
        root / "outputs/repair/r3/validation_summary.json",
        root / "metadata/fed_2026_scenario_manifest.csv",
        root / "configs/stress_specs.yaml",
        root / "configs/macro_series.yaml",
    ]
    for path in paths:
        write_artifact_metadata(
            path, root=root, run_id=R4_RUN_ID, stage="R4", input_artifacts=inputs,
            raw_manifest=root / "data/manifests/ffiec_manifest.csv",
            field_mapping=root / "metadata/field_mapping.csv", validation_status="PASS",
            model_spec=root / "configs/model_specs.yaml",
        )


def run_stress(root: Path, session: requests.sessions.Session | None = None) -> dict[str, Any]:
    """Run the bounded, registry-gated R4 conditional-mean stress rebuild."""
    gate = validate_formal_r4_inputs(root)
    panel = pd.read_parquet(root / "data/derived/model_panel.parquet")
    official = ingest_fed_2026_scenarios(root, session)
    # R2 already embodies source availability.  Use its retained boundary
    # values, then apply only the model's one-quarter carry to the target.
    actual = pd.read_parquet(root / "data/derived/macro_panel.parquet").rename(columns={"report_date": "quarter", "unemployment_rate": "unemployment"})
    _, historic_levels = historic_macro_history(root, session)
    spec = load_stress_specs(root)["stress"]
    sensitivity = make_sensitivity_scenarios(official, historic_levels, spec["lambdas"])
    scenarios = pd.concat([official, sensitivity], ignore_index=True)
    predictors = construct_stress_macro_predictors(scenarios, actual, root)
    macro_predictors = [column for column in predictors if column.startswith("lagged_") and not column.endswith("_source_quarter")]
    for predictor in macro_predictors:
        source = f"{predictor}_source_quarter"
        predictors[f"{predictor}_source_type"] = np.where(
            predictors[source] < predictors["quarter"].min(),
            "R2_MANIFEST_BACKED_HISTORICAL_BOUNDARY",
            np.where(predictors["scenario_type"].eq("Fed official"), "FED_2026_MANIFEST_BACKED_SCENARIO", "RESEARCHER_SENSITIVITY_SCENARIO"),
        )
    jump, exclusions = _r4_jump_off(panel, root)
    models = fit_r4_models(panel, root)
    paths = recursive_r4_paths(jump, predictors, models, loss_rate_floor=float(spec["loss_rate_floor"]))
    summary = _summarize_r4(paths)
    cre_detail, cre_groups = _cre_group_outputs(summary, jump)

    stress_dir = root / "outputs/stress"
    stress_dir.mkdir(parents=True, exist_ok=True)
    paths_path = stress_dir / "stress_paths.parquet"
    summary_path = stress_dir / "conditional_mean_summary.csv"
    paths.to_parquet(paths_path, index=False)
    summary.to_csv(summary_path, index=False)
    cre_detail.to_csv(stress_dir / "cre_group_detail.csv", index=False)
    cre_groups.to_csv(stress_dir / "cre_group_table.csv", index=False)
    exclusions.to_csv(stress_dir / "stress_universe_exclusions.csv", index=False)

    official_paths = paths.loc[paths["scenario"].isin(OFFICIAL_SCENARIOS)]
    t4 = summary.loc[summary["scenario"].isin(OFFICIAL_SCENARIOS)].pivot_table(
        index=["bank_id", "bank_name", "model", "formal_use", "segment", "starting_tier1_thousands", "exposure_thousands"],
        columns="scenario", values="cumulative_loss_thousands", aggfunc="first"
    ).reset_index().rename(columns={"baseline": "baseline_loss_thousands", "severely_adverse": "severe_loss_thousands"})
    t4["severe_modeled_credit_loss_burden"] = t4["severe_loss_thousands"] / t4["starting_tier1_thousands"]
    t4["capital_depletion"] = np.nan
    t4["capital_depletion_reason"] = "Unavailable: limited R4 reports modeled credit-loss burden, not a capital roll-forward"
    t4["mortgage_loss_thousands"] = np.nan
    t4["mortgage_loss_reason"] = "Unavailable: no approved Mortgage stress model"
    t4.to_csv(stress_dir / "t4_fed_stress_results.csv", index=False)

    floor = (paths.groupby(["scenario", "scenario_type", "model", "segment"], as_index=False)
             .agg(floor_use_count=("loss_rate_floor_applied", "sum"), path_rows=("loss_rate_floor_applied", "size"),
                  floored_loss_thousands=("quarter_loss_thousands", "sum"),
                  unfloored_loss_thousands=("quarter_loss_thousands_unfloored", "sum")))
    floor["floor_effect_thousands"] = floor["floored_loss_thousands"] - floor["unfloored_loss_thousands"]
    floor.to_csv(stress_dir / "loss_rate_floor_qa.csv", index=False)

    timing_cols = ["scenario", "scenario_type", "quarter", "horizon"] + [c for c in predictors if c.startswith("lagged_")]
    predictors[timing_cols].to_csv(stress_dir / "macro_predictor_timing.csv", index=False)
    scenario_checks = pd.DataFrame([
        {"check": "manifest_artifacts", "value": 3, "status": "PASS", "detail": "baseline, severely_adverse, historic_domestic hashes matched retained manifest"},
        {"check": "official_horizon_rows", "value": len(official), "status": "PASS" if len(official) == 18 else "FAIL", "detail": "2 scenarios x 9 quarters"},
        {"check": "annualized_nco_rate_unit", "value": 1, "status": "PASS", "detail": "decimal annualized; quarterly loss = rate / 4 * exposure_thousands"},
        {"check": "cre_boundary_definition", "value": 4, "status": "PASS", "detail": "Fed CRE level YoY transformation uses t-4 historical/scenario level"},
        {"check": "house_boundary_definition", "value": 1, "status": "PASS", "detail": "Fed house-price QoQ transformation uses t-1 historical/scenario level"},
    ])
    scenario_checks.to_csv(stress_dir / "scenario_input_validation.csv", index=False)

    sensitivity_rows: list[dict[str, Any]] = []
    for (scenario_name, model, segment), group in summary.groupby(["scenario", "model", "segment"]):
        sensitivity_rows.append({
            "sensitivity": scenario_name, "model": model, "segment": segment,
            "aggregate_cumulative_loss_thousands": group["cumulative_loss_thousands"].sum(),
            "mean_modeled_credit_loss_burden": group["modeled_credit_loss_burden"].mean(),
            "status": "LIMITED_CHALLENGER" if model == "dynamic_fe" else "FORMAL_BASELINE",
        })
    severe_ar = summary.loc[summary["scenario"].eq("severely_adverse") & summary["model"].eq("ar_mean")]
    for change in spec["exposure_sensitivities"]:
        sensitivity_rows.append({
            "sensitivity": f"exposure_{change:+.0%}", "model": "ar_mean", "segment": "CRE+CI",
            "aggregate_cumulative_loss_thousands": severe_ar["cumulative_loss_thousands"].sum() * (1 + change),
            "mean_modeled_credit_loss_burden": severe_ar.groupby("bank_id")["modeled_credit_loss_burden"].sum().mean() * (1 + change),
            "status": "RESEARCHER_SENSITIVITY",
        })
    pd.DataFrame(sensitivity_rows).to_csv(stress_dir / "t5_sensitivity.csv", index=False)

    monotonic_rows = []
    for (model, segment), group in summary.loc[summary["scenario"].isin(OFFICIAL_SCENARIOS)].groupby(["model", "segment"]):
        totals = group.groupby("scenario")["cumulative_loss_thousands"].sum()
        baseline, severe = totals.get("baseline", np.nan), totals.get("severely_adverse", np.nan)
        monotonic_rows.append({"model": model, "segment": segment, "baseline_loss_thousands": baseline,
                               "severe_loss_thousands": severe, "severe_ge_baseline": bool(severe >= baseline),
                               "status": "DIAGNOSTIC_NOT_ENFORCED"})
    monotonic = pd.DataFrame(monotonic_rows)
    monotonic.to_csv(stress_dir / "severity_monotonicity_qa.csv", index=False)

    availability = pd.DataFrame([
        {"model": "ar_mean", "segment": "CI", "formal_status": "ALLOWED", "reporting_role": "formal baseline"},
        {"model": "ar_mean", "segment": "CRE", "formal_status": "ALLOWED", "reporting_role": "formal baseline"},
        {"model": "dynamic_fe", "segment": "CI", "formal_status": "ALLOWED", "reporting_role": "limited challenger; improved RMSE in 1/8 R2 comparisons"},
        {"model": "dynamic_fe", "segment": "CRE", "formal_status": "DIAGNOSTIC_ONLY", "reporting_role": "excluded from formal R4 paths and rankings"},
        {"model": "all_quantile_models", "segment": "CI/CRE", "formal_status": "UNAVAILABLE", "reporting_role": "one-step diagnostic only; no recursive stress or tail ranking"},
        {"model": "bayesian", "segment": "CI/CRE", "formal_status": "NOT_EVALUATED", "reporting_role": "deferred"},
    ])
    availability.to_csv(stress_dir / "model_availability.csv", index=False)

    ci_rank = summary.loc[summary["scenario"].eq("severely_adverse") & summary["segment"].eq("CI")].pivot(index="bank_id", columns="model", values="modeled_credit_loss_burden").dropna()
    n_top = max(1, int(np.ceil(len(ci_rank) / 4)))
    rank = pd.DataFrame([{
        "scenario": "severely_adverse", "segment_scope": "CI_ONLY_COMMON_BANKS", "left_model": "ar_mean", "right_model": "dynamic_fe",
        "n_banks": len(ci_rank), "spearman_rank_correlation": ci_rank["ar_mean"].rank().corr(ci_rank["dynamic_fe"].rank()),
        "top_group_n": n_top,
        "top_group_overlap": len(set(ci_rank.nlargest(n_top, "ar_mean").index) & set(ci_rank.nlargest(n_top, "dynamic_fe").index)) / n_top,
        "status": "LIMITED_CHALLENGER_SENSITIVITY_NOT_FULL_PORTFOLIO_RANKING",
    }])
    rank.to_csv(stress_dir / "ranking_stability.csv", index=False)

    figures = _write_r4_figures(official_paths, cre_detail, root)
    outputs = [
        root / "data/external/fed_2026_scenarios.parquet",
        paths_path, summary_path, stress_dir / "cre_group_detail.csv", stress_dir / "cre_group_table.csv",
        stress_dir / "stress_universe_exclusions.csv", stress_dir / "t4_fed_stress_results.csv",
        stress_dir / "loss_rate_floor_qa.csv", stress_dir / "macro_predictor_timing.csv",
        stress_dir / "scenario_input_validation.csv", stress_dir / "t5_sensitivity.csv",
        stress_dir / "severity_monotonicity_qa.csv", stress_dir / "model_availability.csv",
        stress_dir / "ranking_stability.csv", *figures,
    ]
    _write_r4_sidecars(root, outputs, gate)

    metrics = {
        "run_id": R4_RUN_ID,
        "stress_universe_banks": int(jump["bank_id"].nunique()),
        "formal_path_pairs": [f"{m}/{s}" for m, s in R4_FORMAL_PAIRS],
        "path_rows": int(len(paths)),
        "scenario_manifest_hash": sha256_file(root / "metadata/fed_2026_scenario_manifest.csv"),
        "model_panel_hash": gate["model_panel_hash"],
        "registry_hash": gate["registry_hash"],
        "all_official_severe_ge_baseline": bool(monotonic["severe_ge_baseline"].all()),
    }
    (stress_dir / "run_summary.md").write_text(
        "# R4 limited conditional-mean stress rebuild\n\n"
        f"- Run: `{R4_RUN_ID}`; common stress universe: {metrics['stress_universe_banks']} banks.\n"
        "- Formal baseline: AR mean for C&I and CRE. Limited sensitivity: Dynamic FE for C&I only. Dynamic FE CRE, all quantiles, Bayesian, Mortgage expansion, and multi-period tail claims are excluded.\n"
        "- Paths cover 2026Q1--2028Q1 and retain recursive state, scenario predictors, source quarters, source types, static 2025Q4 exposure, and starting Tier1.\n"
        "- `quarter_loss_thousands = annualized_nco_rate_decimal / 4 * exposure_thousands`. Reported ratios are modeled credit-loss burdens relative to starting Tier1, not capital depletion or CET1 changes.\n"
        "- Severity monotonicity is diagnostic and is not forced. See `severity_monotonicity_qa.csv`.\n",
        encoding="utf-8",
    )
    _write_r4_sidecars(root, [stress_dir / "run_summary.md"], gate)
    return {"paths": paths, "summary": summary, "groups": cre_groups, "stability": rank, "metrics": metrics, "gate": gate}
