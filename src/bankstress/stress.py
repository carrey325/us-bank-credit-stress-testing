"""Batch 4 Fed-scenario stress testing built from the approved Batch 1--3 panel.

This module deliberately produces a credit-loss / starting-Tier-1 result.  It
does not represent the result as a Federal Reserve CET1 projection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
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


def _normalise_fed_frame(frame: pd.DataFrame, scenario: str, historic_q4: pd.Series | None = None) -> pd.DataFrame:
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
    for level, growth in (("cre_price", "cre_price_growth"), ("house_price", "house_price_growth")):
        prior = data[level].shift(1)
        if historic_q4 is not None:
            prior.iloc[0] = float(historic_q4[level])
        data[growth] = data[level].div(prior).sub(1).mul(100)
    return data[["scenario", "quarter", "real_gdp_growth", "gdp_growth", "unemployment", "cre_price", "house_price", "bbb_yield", "mortgage_rate", "short_rate", "long_rate", "bbb_spread", "cre_price_growth", "house_price_growth"]]


def ingest_fed_2026_scenarios(root: Path, session: requests.sessions.Session | None = None) -> pd.DataFrame:
    """Download official final CSVs, transform model variables, and record provenance."""
    spec = load_stress_specs(root)["fed_2026"]
    raw: dict[str, pd.DataFrame] = {}
    manifest: list[dict[str, str]] = []
    for name, key in (("baseline", "baseline_url"), ("severely_adverse", "severely_adverse_url"), ("historic_domestic", "historic_domestic_url")):
        frame, content = _download_csv(spec[key], session)
        raw[name] = frame
        manifest.append({"artifact": name, "source_url": spec[key], "sha256": _sha256(content), "download_timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat()})
    historic = raw["historic_domestic"].copy()
    historic["quarter"] = _quarter_end(historic["Date"])
    q4 = historic.loc[historic["quarter"].eq(pd.Timestamp("2025-12-31"))].iloc[0]
    historic_levels = pd.Series({
        "cre_price": float(q4["Commercial Real Estate Price Index (Level)"]),
        "house_price": float(q4["House Price Index (Level)"]),
        "short_rate": float(q4["3-month Treasury rate"]),
        "long_rate": float(q4["10-year Treasury yield"]),
        "mortgage_rate": float(q4["Mortgage rate"]),
    })
    scenario = pd.concat([_normalise_fed_frame(raw[name], name, historic_levels) for name in OFFICIAL_SCENARIOS], ignore_index=True)
    start, end = pd.Timestamp(spec["primary_start"]), pd.Timestamp(spec["primary_end"])
    scenario = scenario[scenario.quarter.between(start, end)].copy()
    scenario["horizon"] = scenario.groupby("scenario").cumcount() + 1
    scenario["scenario_type"] = "Fed official"
    external = root / "data" / "external"
    external.mkdir(parents=True, exist_ok=True)
    scenario.to_parquet(external / "fed_2026_scenarios.parquet", index=False)
    pd.DataFrame(manifest).to_csv(root / "metadata" / "fed_2026_scenario_manifest.csv", index=False)
    return scenario


def historic_macro_history(root: Path, session: requests.sessions.Session | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Return transformed Fed history used to seed the Batch 2 macro interface."""
    url = load_stress_specs(root)["fed_2026"]["historic_domestic_url"]
    historic, _ = _download_csv(url, session)
    historic["quarter"] = _quarter_end(historic["Date"])
    normalized = _normalise_fed_frame(historic.drop(columns="quarter"), "actual")
    required = {pd.Timestamp("2025-09-30"), pd.Timestamp("2025-12-31")}
    if not required.issubset(set(normalized["quarter"])):
        raise ValueError("Fed historic domestic data lacks the 2025Q3/Q4 macro state")
    source_q4 = historic.loc[historic.quarter.eq(pd.Timestamp("2025-12-31"))].iloc[0]
    levels = pd.Series({"cre_price": float(source_q4["Commercial Real Estate Price Index (Level)"]), "house_price": float(source_q4["House Price Index (Level)"]), "short_rate": float(source_q4["3-month Treasury rate"]), "long_rate": float(source_q4["10-year Treasury yield"]), "mortgage_rate": float(source_q4["Mortgage rate"])})
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


def make_sensitivity_scenarios(official: pd.DataFrame, historic_rates: pd.Series, lambdas: list[float]) -> pd.DataFrame:
    """Create clearly-labelled researcher sensitivities from the fixed official paths."""
    baseline = official[official.scenario.eq("baseline")].sort_values("quarter").reset_index(drop=True)
    severe = official[official.scenario.eq("severely_adverse")].sort_values("quarter").reset_index(drop=True)
    if not baseline.quarter.equals(severe.quarter):
        raise ValueError("Official baseline and severely-adverse quarters do not align")
    numeric = [column for column in baseline if column not in {"scenario", "quarter", "horizon", "scenario_type"}]
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
        # Recompute growth fields after interpolating price levels, preserving Q1
        # first-period changes by interpolating the historical level consistently.
        for level, growth in (("cre_price", "cre_price_growth"), ("house_price", "house_price_growth")):
            previous = item[level].shift(1)
            prior_level = float(historic_rates[level]) + float(value) * (float(historic_rates[level]) - float(historic_rates[level]))
            previous.iloc[0] = prior_level
            item[growth] = item[level].div(previous).sub(1).mul(100)
        rows.append(item)
    cre = baseline.copy()
    cre["cre_price"] = severe["cre_price"].to_numpy()
    cre["cre_price_growth"] = severe["cre_price_growth"].to_numpy()
    cre["scenario"], cre["scenario_type"] = "researcher_cre_only", "Researcher partial-shock sensitivity"
    unemployment = baseline.copy()
    unemployment["unemployment"] = severe["unemployment"].to_numpy()
    unemployment["scenario"], unemployment["scenario_type"] = "researcher_unemployment_only", "Researcher partial-shock sensitivity"
    rates = baseline.copy()
    for column in ("short_rate", "long_rate", "mortgage_rate"):
        rates[column] = float(historic_rates[column])
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


def run_batch4(root: Path, session: requests.sessions.Session | None = None) -> dict[str, Any]:
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
        "- 2026Q1 bank controls use the actual 2025Q4 current state and remain static. GDP/unemployment scenario features first affect 2026Q2, while final-vintage fallback features first affect 2026Q3 because Batch 2 applies their documented availability lag and the model then applies its own lag; `macro_predictor_timing.csv` records all sources.\n"
        f"- Dollar-loss floor use: {int(floor_qa.floor_use_count.sum())} of {int(floor_qa.path_observations.sum())} path observations; see `loss_rate_floor_qa.csv`. Mortgage attribution is unavailable, not zero-filled, because no approved mortgage stress model exists.\n"
        "- Bayesian ranking is unavailable because Batch 3 recorded no usable posterior forecasts; it is not imputed.\n", encoding="utf-8")
    return {"paths": paths, "summary": summaries, "groups": groups, "stability": stability, "metrics": metrics}
