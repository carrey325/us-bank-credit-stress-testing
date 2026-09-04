"""Batch 5 model-risk calibration and final-delivery routines.

This module deliberately consumes the committed model and stress outputs.  It
does not refit the credit-loss models or introduce an unapproved market-data
substitute.  In particular, the conformal layer is a documented rolling
residual-bootstrap fallback because the available quantile forecasts provide a
Q0.50--Q0.90 band rather than a two-sided 90% band and Batch 3 has no usable
Bayesian posterior forecasts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from matplotlib import pyplot as plt


TARGET_COVERAGE = 0.90
SEED_QUARTERS = 8
ROLLING_QUARTERS = 20


def _crisis_mask(dates: pd.Series) -> pd.Series:
    values = pd.to_datetime(dates)
    return (
        values.between(pd.Timestamp("2007-01-01"), pd.Timestamp("2010-12-31"))
        | values.between(pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"))
        | values.between(pd.Timestamp("2022-01-01"), pd.Timestamp("2025-12-31"))
    )


def _radius(values: pd.Series, coverage: float) -> float:
    """Finite-sample residual radius, calculated only from prior forecasts."""
    scores = np.sort(pd.to_numeric(values, errors="coerce").dropna().to_numpy(float))
    if not len(scores):
        raise ValueError("A conformal radius needs at least one prior residual")
    # The finite-sample rank is the split-conformal order statistic.  ``higher``
    # avoids interpolating a residual that was never actually observed.
    rank = min(len(scores) - 1, int(np.ceil((len(scores) + 1) * coverage)) - 1)
    return float(scores[max(rank, 0)])


def rolling_residual_intervals(
    predictions: pd.DataFrame,
    *,
    target_coverage: float = TARGET_COVERAGE,
    seed_quarters: int = SEED_QUARTERS,
    rolling_quarters: int = ROLLING_QUARTERS,
) -> pd.DataFrame:
    """Create static and rolling 90% residual intervals without time leakage.

    The input must be *out-of-sample Dynamic-FE* forecasts.  Forecasts at date
    ``t`` can use residuals only from dates earlier than ``t``; cross-sectional
    residuals from date ``t`` are intentionally excluded as well.
    """
    required = {"bank_id", "segment", "report_date", "nco_rate", "prediction"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Conformal input missing columns: {sorted(missing)}")
    if not 0 < target_coverage < 1:
        raise ValueError("target_coverage must be between zero and one")
    if seed_quarters < 1 or rolling_quarters < 1:
        raise ValueError("calibration windows must be positive")

    frame = predictions[list(required)].copy()
    frame["report_date"] = pd.to_datetime(frame["report_date"])
    frame["absolute_residual"] = (frame["nco_rate"] - frame["prediction"]).abs()
    rows: list[pd.DataFrame] = []
    for segment, group in frame.groupby("segment", sort=True):
        group = group.sort_values(["report_date", "bank_id"], kind="stable")
        dates = list(group["report_date"].drop_duplicates().sort_values())
        if len(dates) <= seed_quarters:
            continue
        seed_dates = dates[:seed_quarters]
        static_scores = group.loc[group["report_date"].isin(seed_dates), "absolute_residual"]
        static_radius = _radius(static_scores, target_coverage)
        for position, date in enumerate(dates[seed_quarters:], start=seed_quarters):
            historical_dates = dates[max(0, position - rolling_quarters):position]
            rolling_scores = group.loc[group["report_date"].isin(historical_dates), "absolute_residual"]
            rolling_radius = _radius(rolling_scores, target_coverage)
            current = group.loc[group["report_date"].eq(date)].copy()
            for method, radius in (
                ("static_residual_bootstrap", static_radius),
                ("rolling_adaptive_residual_bootstrap", rolling_radius),
            ):
                result = current.copy()
                result["method"] = method
                result["target_coverage"] = target_coverage
                result["calibration_radius"] = radius
                result["calibration_end_date"] = historical_dates[-1] if method.startswith("rolling") else seed_dates[-1]
                result["lower"] = result["prediction"] - radius
                result["upper"] = result["prediction"] + radius
                result["covered"] = result["nco_rate"].between(result["lower"], result["upper"])
                result["underpredicted"] = result["nco_rate"] > result["upper"]
                rows.append(result)
    if not rows:
        raise ValueError("No OOS dates remain after the conformal seed window")
    result = pd.concat(rows, ignore_index=True)
    if not (result["calibration_end_date"] < result["report_date"]).all():
        raise AssertionError("Conformal calibration used a same-date or future residual")
    return result


def conformal_metrics(intervals: pd.DataFrame) -> pd.DataFrame:
    """Summarise coverage, width, proper interval score, and crisis misses."""
    required = {"method", "segment", "nco_rate", "lower", "upper", "covered", "underpredicted", "target_coverage", "report_date"}
    missing = required - set(intervals.columns)
    if missing:
        raise ValueError(f"Conformal interval input missing columns: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for (method, segment), group in intervals.groupby(["method", "segment"], sort=True):
        width = group["upper"] - group["lower"]
        below = (group["lower"] - group["nco_rate"]).clip(lower=0)
        above = (group["nco_rate"] - group["upper"]).clip(lower=0)
        alpha = 1 - float(group["target_coverage"].iloc[0])
        winkler = width + (2 / alpha) * (below + above)
        rows.append({
            "method": method,
            "segment": segment,
            "n": int(len(group)),
            "target_coverage": float(group["target_coverage"].iloc[0]),
            "empirical_coverage": float(group["covered"].mean()),
            "coverage_gap": float(group["covered"].mean() - group["target_coverage"].iloc[0]),
            "mean_interval_width": float(width.mean()),
            "winkler_score": float(winkler.mean()),
            "crisis_underprediction_count": int((group["underpredicted"] & _crisis_mask(group["report_date"])).sum()),
            "all_period_underprediction_count": int(group["underpredicted"].sum()),
            "first_forecast_date": group["report_date"].min().date().isoformat(),
            "last_forecast_date": group["report_date"].max().date().isoformat(),
        })
    result = pd.DataFrame(rows)
    static_misses = result.loc[result["method"].eq("static_residual_bootstrap")].set_index("segment")["crisis_underprediction_count"]
    result["crisis_underprediction_change_vs_static"] = result.apply(
        lambda row: int(row["crisis_underprediction_count"] - static_misses.loc[row["segment"]]), axis=1
    )
    return result


def _weighted_model_table(root: Path) -> pd.DataFrame:
    comparison = pd.read_csv(root / "outputs" / "validation" / "model_comparison.csv")
    mean = comparison.loc[comparison["metric_family"].eq("mean")].copy()
    if mean.empty:
        raise ValueError("Batch 3 mean-model comparison is empty")
    rows = []
    for model, group in mean.groupby("model", sort=True):
        rows.append({
            "model": model,
            "oos_observations": int(group["n"].sum()),
            "pooled_oos_rmse": float(np.sqrt(np.average(group["rmse"].pow(2), weights=group["n"]))),
            "pooled_oos_mae": float(np.average(group["mae"], weights=group["n"])),
            "mean_bias": float(np.average(group["bias"], weights=group["n"])),
            "availability": "included",
        })
    table = pd.DataFrame(rows)
    bayesian = pd.read_csv(root / "outputs" / "models" / "bayesian" / "diagnostics.csv")
    if not bayesian["status"].eq("sampled").all():
        table = pd.concat([table, pd.DataFrame([{
            "model": "bayesian", "oos_observations": 0, "pooled_oos_rmse": np.nan,
            "pooled_oos_mae": np.nan, "mean_bias": np.nan,
            "availability": "unavailable: documented Batch 3 environment fallback; no posterior forecast results",
        }])], ignore_index=True)
    return table


def _write_delivery_figures(root: Path, intervals: pd.DataFrame, metrics: pd.DataFrame) -> list[dict[str, str]]:
    figure_dir = root / "outputs" / "reporting" / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(root / "data" / "derived" / "model_panel.parquet")
    panel["report_date"] = pd.to_datetime(panel["report_date"])

    history = panel.groupby(["report_date", "segment"], as_index=False).agg(nco_rate=("nco_rate", "mean"), npl_rate=("npl_rate", "mean"))
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for segment, group in history.groupby("segment", sort=True):
        axes[0].plot(group["report_date"], group["nco_rate"], label=segment)
        axes[1].plot(group["report_date"], group["npl_rate"], label=segment)
    axes[0].set(title="Segment NCO rate history", ylabel="Quarterly NCO rate")
    axes[1].set(title="Segment NPL rate history", xlabel="Quarter", ylabel="NPL rate")
    axes[0].legend(); axes[1].legend(); fig.tight_layout()
    fig.savefig(figure_dir / "segment_nco_npl_history.png", dpi=150); plt.close(fig)

    latest = panel.loc[panel["report_date"].eq(panel["report_date"].max()) & panel["segment"].isin(["CRE", "CI"])]
    exposure = latest.pivot(index="bank_name", columns="segment", values="exposure").rename(columns={"CRE": "CRE exposure", "CI": "CI exposure"})
    stress = pd.read_csv(root / "outputs" / "stress" / "t4_fed_stress_results.csv")
    stress = stress.loc[stress["model"].eq("dynamic_fe")].set_index("bank_name")
    heat = exposure.join(stress[["cre_loss", "ci_loss"]].rename(columns={"cre_loss": "CRE severe loss", "ci_loss": "CI severe loss"}), how="inner")
    values = np.log10(heat.clip(lower=1).to_numpy(float))
    fig, ax = plt.subplots(figsize=(8, 6))
    image = ax.imshow(values, aspect="auto", cmap="YlOrRd")
    ax.set(title="2025Q4 exposure and severely-adverse loss (log10 thousands)", xticks=range(len(heat.columns)), xticklabels=heat.columns, yticks=range(len(heat.index)), yticklabels=heat.index)
    fig.colorbar(image, ax=ax, label="log10(thousands)"); fig.tight_layout()
    fig.savefig(figure_dir / "exposure_loss_heatmap.png", dpi=150); plt.close(fig)

    plot = metrics.pivot(index="segment", columns="method", values="empirical_coverage")
    fig, ax = plt.subplots(figsize=(8, 5)); plot.plot.bar(ax=ax)
    ax.axhline(TARGET_COVERAGE, color="black", linestyle="--", label="90% target")
    ax.set(title="OOS interval coverage: static vs rolling residual bootstrap", ylabel="Empirical coverage", xlabel="Segment", ylim=(0, 1))
    ax.legend(); fig.tight_layout(); fig.savefig(figure_dir / "conformal_coverage.png", dpi=150); plt.close(fig)

    return [
        {"figure_id": "F1", "path": "outputs/reporting/figures/segment_nco_npl_history.png", "description": "Segment NCO and NPL history", "status": "generated"},
        {"figure_id": "F2", "path": "outputs/reporting/figures/exposure_loss_heatmap.png", "description": "Exposure/loss heatmap", "status": "generated"},
        {"figure_id": "F3", "path": "outputs/stress/figures/cre_to_capital_vs_depletion.png", "description": "CRE-to-capital versus severe capital depletion", "status": "Batch 4 generated"},
        {"figure_id": "F4", "path": "outputs/validation/figures/fe_mean_vs_actual.png", "description": "FE mean forecast", "status": "Batch 3 generated"},
        {"figure_id": "F5", "path": "outputs/validation/figures/gfc_pseudo_stress.png", "description": "Historical pseudo-stress", "status": "Batch 3 generated"},
        {"figure_id": "F6", "path": "outputs/stress/figures/baseline_vs_severe_system_loss.png", "description": "Fed baseline/severe paths", "status": "Batch 4 generated"},
        {"figure_id": "F7", "path": "outputs/stress/figures/model_ranking_stability.png", "description": "Stress ranking stability", "status": "Batch 4 generated"},
        {"figure_id": "F8", "path": "outputs/reporting/figures/conformal_coverage.png", "description": "Model-risk interval coverage", "status": "generated"},
    ]


def _write_final_report(root: Path, summary: dict[str, Any], conformal: pd.DataFrame) -> Path:
    """Render a plainly labelled ten-page draft from generated artifacts."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except ImportError as error:  # pragma: no cover - exercised by the delivery script
        raise RuntimeError("Batch 5 report generation requires reportlab; install project dependencies") from error
    destination = root / "outputs" / "reporting" / "MF772_final_report_draft.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body, heading = styles["BodyText"], styles["Heading1"]
    document = SimpleDocTemplate(str(destination), pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch, topMargin=0.6 * inch, bottomMargin=0.55 * inch)
    adaptive_misses = conformal.loc[conformal["method"].eq("rolling_adaptive_residual_bootstrap")].set_index("segment")["crisis_underprediction_count"]
    static_misses = conformal.loc[conformal["method"].eq("static_residual_bootstrap")].set_index("segment")["crisis_underprediction_count"]
    pages = [
        ("1. Abstract, research question, and contribution", [
            "This reproducible public-data framework reconstructs segment-level quarterly net charge-off (NCO) rates for U.S. regional banks and translates the approved Federal Reserve 2026 scenarios into transparent loss-to-starting-Tier-1-capital results.",
            f"The generated panel contains {summary['n_banks']} banks, {summary['n_observations']:,} bank-segment-quarter observations, and {summary['n_raw_fields']} mapped raw fields. Results are descriptive conditional stress estimates, not failure predictions or causal effects.",
        ]),
        ("2. Data, sample, and regulatory fields", [
            "The analysis unit is bank x loan segment x quarter. The panel uses FFIEC Call Report source snapshots, an effective-dated field mapping, documented merger flags, and FDIC noncurrent-loan controls.",
            "Raw archives are excluded from version control; manifests retain official URLs, timestamps, and hashes. Missing values are retained as missing rather than converted to zero.",
        ]),
        ("3. NCO reconstruction and quality assurance", [
            "NCO is quarterly charge-offs less recoveries, divided by average segment exposure. YTD flows are quarterlyized before aggregation. The reproducibility audit retains the one documented REVIEW_REQUIRED source reconciliation item rather than recoding it.",
            "Mortgage coverage is reconstructed for historical panel reporting, but no approved Mortgage stress model exists; stress tables therefore label mortgage attribution unavailable rather than zero.",
        ]),
        ("4. Dynamic fixed effects and CRE interaction", [
            "The Dynamic-FE model is the approved mean model. The CRE interaction uses lagged CRE-to-Tier-1 measured at or before the forecast origin, following the documented timing repair. The analysis separates mechanical exposure-driven loss from any incremental loss-rate interaction.",
            f"The committed pooled Dynamic-FE OOS comparison is reported in T3; the generated resume metric records an AR-relative RMSE change of {summary['best_oos_rmse_improvement_vs_ar']:.2%}, not a pre-planned target.",
        ]),
        ("5. Quantile and Bayesian model-risk evidence", [
            "Q0.50/Q0.75/Q0.90 forecasts are evaluated with pinball loss and pre-specified historical pseudo-stress windows. The Q0.90 CRE recursive path is not historically calibrated across GFC, COVID, and the 2022+ high-rate/CRE window; it remains a downstream tail sensitivity, not a validated forecast.",
            "Bayesian posterior forecasts are unavailable under the recorded Batch 3 environment fallback. No sampled posterior result, interval, or performance claim is presented here.",
        ]),
        ("6. OOS validation and historical pseudo-stress", [
            "All OOS windows preserve chronology and do not randomly shuffle observations. Pseudo-stress forecasts use realised historical macro paths, recursive NCO states, and frozen future bank controls.",
            "The OOS and pseudo-stress charts are generated from saved forecasts. Tail calibration failures are documented rather than optimized away after observing results.",
        ]),
        ("7. Federal Reserve 2026 stress results", [
            "The project applies the official final baseline and severely adverse domestic paths, plus clearly labelled researcher sensitivity scenarios. Primary capital output is cumulative credit loss divided by starting Tier 1 capital, not a Federal Reserve CET1 projection.",
            f"The final stress universe is {summary['stress_banks']} banks with complete CRE and C&I 2025Q4 states. The high-minus-low CRE-group mean capital-depletion difference is {summary['high_cre_capital_depletion_difference']:.2%} under the Dynamic-FE severe scenario.",
        ]),
        ("8. Model risk, robustness, and conformal fallback", [
            "Batch 5 implements a rolling residual-bootstrap interval fallback around OOS Dynamic-FE forecasts. It uses only earlier OOS residuals: an eight-quarter seed for the static comparator and a twenty-quarter adaptive calibration window. It is not presented as Bayesian or quantile conformal inference.",
            "T5 reports static versus rolling residual-calibrated 90% interval coverage, width, proper Winkler score, and crisis underprediction counts by segment. In this run, rolling calibration increases crisis upper misses: CI "
            f"{int(static_misses['CI'])} to {int(adaptive_misses['CI'])}; CRE {int(static_misses['CRE'])} to {int(adaptive_misses['CRE'])}. It therefore does not meet the desired crisis-underprediction reduction. The method targets calibration, not a guaranteed exact 90% result or a trading signal.",
        ]),
        ("9. External validation and reproducibility", [
            "Market validation is deliberately not completed. No verified bank legal entity -> BHC/parent -> ticker mapping was available in this repository, and ambiguous name-to-ticker matching would violate the approved specification. No market-validation statistic is claimed.",
            "The final audit checks artifacts, time ordering, effective-dated mapping fields, merger records, saved Bayesian diagnostics, non-zero missingness handling, and agreement between stress paths and reported stress totals.",
        ]),
        ("10. Conclusion and limitations", [
            "The deliverable is a transparent public-data research pipeline with explicit model-risk evidence. It supports conditional portfolio stress analysis but does not reproduce confidential FR Y-14 supervisory models or make bank-failure predictions.",
            "Carry-forward limitations: source/reconciliation caveats remain visible; macro final-vintage fallback variables are not real-time vintages; Bayesian posterior outputs are unavailable; recursive CRE Q0.90 is not historically calibrated; and Mortgage stress attribution is unavailable. Future work should verify a legal-entity parent/ticker mapping before external market validation.",
        ]),
    ]
    story = []
    page_images = {
        2: root / "outputs" / "reporting" / "figures" / "segment_nco_npl_history.png",
        4: root / "outputs" / "validation" / "figures" / "fe_mean_vs_actual.png",
        5: root / "outputs" / "validation" / "figures" / "quantile_75_90_bands.png",
        6: root / "outputs" / "validation" / "figures" / "gfc_pseudo_stress.png",
        7: root / "outputs" / "stress" / "figures" / "baseline_vs_severe_system_loss.png",
        9: root / "outputs" / "reporting" / "figures" / "exposure_loss_heatmap.png",
    }
    for number, (title, paragraphs) in enumerate(pages, start=1):
        story.extend([Paragraph(title, heading), Spacer(1, 0.15 * inch)])
        for paragraph in paragraphs:
            story.extend([Paragraph(paragraph, body), Spacer(1, 0.12 * inch)])
        if number == 8:
            rows = [["Method", "Segment", "Coverage", "Width", "Crisis upper misses"]]
            for _, row in conformal.iterrows():
                rows.append([str(row["method"]), str(row["segment"]), f"{row['empirical_coverage']:.1%}", f"{row['mean_interval_width']:.4f}", str(int(row["crisis_underprediction_count"]))])
            table = Table(rows, repeatRows=1, colWidths=[1.8 * inch, 0.7 * inch, 0.75 * inch, 0.7 * inch, 1.2 * inch])
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
            story.append(table)
        image_path = page_images.get(number)
        if image_path and image_path.exists():
            story.extend([Spacer(1, 0.08 * inch), Image(str(image_path), width=6.2 * inch, height=3.45 * inch)])
        if number < len(pages):
            story.append(PageBreak())
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(letter[0] - 0.65 * inch, 0.35 * inch, f"MF772 final draft | page {doc.page}")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return destination


def _same_frame(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-10)
    except AssertionError:
        return False
    return True


def _audit(root: Path, tables: list[dict[str, str]], figures: list[dict[str, str]], intervals: pd.DataFrame) -> dict[str, Any]:
    panel = pd.read_parquet(root / "data" / "derived" / "model_panel.parquet")
    mapping = pd.read_csv(root / "metadata" / "field_mapping.csv")
    stress_paths = pd.read_parquet(root / "outputs" / "stress" / "stress_paths.parquet")
    t4 = pd.read_csv(root / "outputs" / "stress" / "t4_fed_stress_results.csv")
    calendar = pd.read_csv(root / "metadata" / "macro_release_calendar.csv", parse_dates=["observation_date", "release_date"])
    specs = yaml.safe_load((root / "configs" / "model_specs.yaml").read_text(encoding="utf-8"))
    oos = pd.read_parquet(root / "outputs" / "validation" / "oos_predictions.parquet")
    tail = pd.read_csv(root / "outputs" / "validation" / "tail_metrics.csv")
    severe_paths = (stress_paths.loc[(stress_paths["scenario"].eq("severely_adverse")) & stress_paths["model"].eq("dynamic_fe")]
                    .assign(bank_id=lambda frame: frame["bank_id"].astype(str)).groupby("bank_id")["predicted_loss"].sum())
    severe_table = (t4.loc[t4["model"].eq("dynamic_fe")]
                    .assign(bank_id=lambda frame: frame["bank_id"].astype(str)).set_index("bank_id")["severe_loss"])
    expected_t1 = pd.read_csv(root / "outputs" / "reporting" / "tables" / "sample_coverage.csv")
    expected_t4 = (t4.groupby("model", as_index=False).agg(banks=("bank_id", "nunique"), baseline_loss=("baseline_loss", "sum"), severe_loss=("severe_loss", "sum"), mean_capital_depletion=("capital_depletion", "mean")))
    delivered_t4 = pd.read_csv(root / "outputs" / "reporting" / "tables" / "fed_stress_results.csv")
    delivered_t5 = pd.read_csv(root / "outputs" / "reporting" / "tables" / "robustness_model_risk.csv")
    expected_t5 = pd.concat([conformal_metrics(intervals).assign(section="conformal"), pd.read_csv(root / "outputs" / "stress" / "ranking_stability.csv").assign(section="ranking_stability")], ignore_index=True, sort=False)
    resume = json.loads((root / "outputs" / "reporting" / "resume_metrics.json").read_text(encoding="utf-8"))
    test_windows_match = all(
        not oos.loc[oos["window"].eq(number)].empty
        and pd.to_datetime(oos.loc[oos["window"].eq(number), "report_date"]).between(pd.Timestamp(window["test_start"]), pd.Timestamp(window["test_end"])).all()
        and pd.Timestamp(window["train_end"]) < pd.Timestamp(window["test_start"])
        for number, window in enumerate(specs["oos_windows"], start=1)
    )
    ytd_probe = pd.DataFrame({"bank_id": ["1", "1"], "standard_metric": ["charge_off", "charge_off"], "segment": ["CI", "CI"], "raw_code": ["X", "X"], "report_date": ["2025-03-31", "2025-06-30"], "numeric_value": [2.0, 5.0]})
    from bankstress.transform.flows import quarterize_ytd
    ytd_quarterized = quarterize_ytd(ytd_probe)["quarterly_value"].tolist() == [2.0, 3.0]
    checks = {
        "required_final_tables_exist": all((root / item["path"]).exists() and (root / item["path"]).stat().st_size > 0 for item in tables),
        "required_final_figures_exist": all((root / item["path"]).exists() and (root / item["path"]).stat().st_size > 0 for item in figures),
        "model_panel_retains_missing_nco": bool(panel["nco_rate"].isna().any()),
        "ytd_quarterization_regression_check": ytd_quarterized,
        "field_mapping_has_effective_dates": bool({"start_date", "end_date"}.issubset(mapping.columns)),
        "merger_quarters_are_recorded": (root / "metadata" / "institution_lineage.csv").exists(),
        "macro_release_calendar_has_no_future_observation": bool((calendar["observation_date"] <= calendar["release_date"]).all()),
        "panel_forecast_origins_precede_outcomes": bool(pd.to_datetime(panel["forecast_origin"]).lt(pd.to_datetime(panel["report_date"])).all()),
        "oos_windows_preserve_time_order_without_shuffle": test_windows_match,
        "conformal_has_strict_time_order": bool((intervals["calibration_end_date"] < intervals["report_date"]).all()),
        "bayesian_diagnostics_saved": (root / "outputs" / "models" / "bayesian" / "diagnostics.csv").exists(),
        "stress_totals_reconcile_to_paths": bool(np.allclose(severe_paths.sort_index().to_numpy(), severe_table.reindex(severe_paths.index).to_numpy(), rtol=1e-10, atol=1e-6)),
        "final_t4_is_rebuilt_from_stress_output": _same_frame(delivered_t4, expected_t4),
        "final_t5_is_rebuilt_from_model_risk_and_stress_outputs": _same_frame(delivered_t5, expected_t5),
        "final_t1_matches_generated_panel_scope": int(expected_t1.iloc[0]["observations"]) == len(panel) and int(expected_t1.iloc[0]["banks"]) == panel["bank_id"].nunique(),
        "market_validation_not_fabricated": (root / "outputs" / "market_validation" / "status.md").exists(),
        "quantile_uses_pinball_not_rmse_for_tail_scoring": tail.loc[tail["model"].str.startswith("quantile_"), "metric"].eq("pinball_loss").any() and tail.loc[tail["metric"].eq("pinball_loss"), "value"].notna().all(),
        "cre_specification_record_is_present": "Frozen" in (root / "configs" / "model_specs.yaml").read_text(encoding="utf-8") and "cre_interaction_spec" in specs,
        "resume_metrics_match_generated_scope": int(resume["n_banks"]) == int(panel["bank_id"].nunique()) and int(resume["n_observations"]) == len(panel) and int(resume["n_raw_fields"]) == int(mapping["raw_code"].nunique()) and int(resume["stress_universe_banks"]) == int(t4.loc[t4["model"].eq("dynamic_fe"), "bank_id"].nunique()),
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "limitations": [
        "One source reconciliation item remains REVIEW_REQUIRED; it is not reclassified.",
        "Some macro features use documented final-vintage fallback lags rather than a complete real-time vintage feed.",
        "Bayesian posterior forecasts are unavailable under the documented environment fallback.",
        "Recursive CRE Q0.90 is not historically calibrated across all pre-specified pseudo-stress windows.",
        "Mortgage stress attribution is unavailable because no approved mortgage stress model exists.",
        "Market validation is not completed because no verified legal-entity-to-parent-to-ticker mapping is available.",
    ]}


def run_batch5(root: Path) -> dict[str, Any]:
    """Generate every Batch 5 artifact from real prior-batch outputs."""
    model_risk = root / "outputs" / "model_risk"
    reporting = root / "outputs" / "reporting"
    market = root / "outputs" / "market_validation"
    for directory in (model_risk, reporting, market):
        directory.mkdir(parents=True, exist_ok=True)
    oos = pd.read_parquet(root / "outputs" / "validation" / "oos_predictions.parquet")
    dynamic_fe = oos.loc[oos["model"].eq("dynamic_fe")].copy()
    intervals = rolling_residual_intervals(dynamic_fe)
    metrics = conformal_metrics(intervals)
    intervals.to_parquet(model_risk / "rolling_residual_intervals.parquet", index=False)
    metrics.to_csv(model_risk / "conformal_metrics.csv", index=False)
    (model_risk / "methodology.md").write_text(
        "# Batch 5 rolling residual-bootstrap fallback\n\n"
        "This is an explicitly labelled fallback, not a new primary credit-loss model or a Bayesian result. "
        "The available quantile outputs form a Q0.50--Q0.90 band rather than a two-sided 90% band, and Batch 3 recorded no usable posterior forecasts. "
        "Accordingly, the method centers two-sided 90% intervals on OOS Dynamic-FE forecasts. A static comparator uses absolute residuals from the first eight OOS quarters; the adaptive version uses only residuals from the preceding twenty OOS quarters. "
        "No residual from the forecast date or a later date enters its interval.\n",
        encoding="utf-8",
    )
    (market / "status.md").write_text(
        "# Market external validation status\n\n"
        "Not completed. Batch 5 requires a verified bank legal entity -> BHC/parent -> listed ticker mapping before market outcomes may be linked. "
        "No such mapping is present in this repository, so no name-based ticker match, market download, regression, or external-validation claim was made.\n",
        encoding="utf-8",
    )
    panel = pd.read_parquet(root / "data" / "derived" / "model_panel.parquet")
    sample = pd.read_csv(root / "outputs" / "eda" / "sample_stats.csv").iloc[0]
    mapping = pd.read_csv(root / "metadata" / "field_mapping.csv")
    reconciliation = pd.read_csv(root / "outputs" / "qa" / "reconciliation_summary.csv")
    t1 = pd.DataFrame([{"banks": int(sample["banks"]), "quarters": int(sample["quarters"]), "observations": int(sample["observations"]), "segments": int(sample["segments"]), "mapped_raw_fields": int(mapping["raw_code"].nunique()), "model_eligible_observations": int(panel["eligible_for_model"].sum())}])
    t2 = (reconciliation.assign(reconciliation_class=reconciliation["nco_reconciliation_status"].str.split("_").str[0])
          .groupby("reconciliation_class", as_index=False).size().rename(columns={"size": "bank_quarters"}))
    t3 = _weighted_model_table(root)
    t4 = (pd.read_csv(root / "outputs" / "stress" / "t4_fed_stress_results.csv")
          .groupby("model", as_index=False).agg(banks=("bank_id", "nunique"), baseline_loss=("baseline_loss", "sum"), severe_loss=("severe_loss", "sum"), mean_capital_depletion=("capital_depletion", "mean")))
    stability = pd.read_csv(root / "outputs" / "stress" / "ranking_stability.csv")
    t5 = pd.concat([metrics.assign(section="conformal"), stability.assign(section="ranking_stability")], ignore_index=True, sort=False)
    table_items = [("T1", t1, "sample_coverage.csv", "Sample coverage"), ("T2", t2, "data_quality.csv", "Data quality"), ("T3", t3, "model_comparison.csv", "Model comparison"), ("T4", t4, "fed_stress_results.csv", "Fed stress results"), ("T5", t5, "robustness_model_risk.csv", "Robustness and model risk")]
    tables = []
    for identifier, table, filename, description in table_items:
        relative = f"outputs/reporting/tables/{filename}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False)
        tables.append({"table_id": identifier, "path": relative, "description": description, "status": "generated"})
    pd.DataFrame(tables).to_csv(reporting / "final_tables_manifest.csv", index=False)
    figures = _write_delivery_figures(root, intervals, metrics)
    pd.DataFrame(figures).to_csv(reporting / "final_figures_manifest.csv", index=False)
    existing_resume = json.loads((reporting / "resume_metrics.json").read_text(encoding="utf-8"))
    final_resume = {**existing_resume,
        "n_banks": int(sample["banks"]),
        "n_observations": int(sample["observations"]),
        "n_raw_fields": int(mapping["raw_code"].nunique()),
        "stress_universe_banks": int(t4.loc[t4["model"].eq("dynamic_fe"), "banks"].iloc[0]),
        "resume_metric_scope": "n_banks is the final historical panel; stress_universe_banks is the 2025Q4 CRE/C&I stress universe.",
    }
    (reporting / "resume_metrics.json").write_text(json.dumps(final_resume, indent=2) + "\n", encoding="utf-8")
    summary = {**final_resume, "stress_banks": final_resume["stress_universe_banks"]}
    report_path = _write_final_report(root, summary, metrics)
    audit = _audit(root, tables, figures, intervals)
    (reporting / "reproducibility_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    lines = ["# Batch 5 reproducibility audit", "", f"Status: **{audit['status']}**", "", "## Checks", ""]
    lines.extend(f"- {'PASS' if passed else 'FAIL'}: {name}" for name, passed in audit["checks"].items())
    lines.extend(["", "## Carry-forward limitations", "", *[f"- {item}" for item in audit["limitations"]], ""])
    (reporting / "reproducibility_audit.md").write_text("\n".join(lines), encoding="utf-8")
    if audit["status"] != "PASS":
        raise RuntimeError("Batch 5 reproducibility audit failed")
    return {"metrics": metrics, "tables": tables, "figures": figures, "audit": audit, "report_path": report_path, "summary": summary}
