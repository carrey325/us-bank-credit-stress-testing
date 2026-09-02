"""Batch 2 descriptive outputs generated from the actual model panel."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def write_eda(panel: pd.DataFrame, root: Path) -> None:
    path = root / "outputs" / "eda"
    path.mkdir(parents=True, exist_ok=True)
    stats = pd.DataFrame([{"banks": panel.bank_id.nunique(), "segments": panel.segment.nunique(), "quarters": panel.report_date.nunique(),
                           "observations": len(panel), "exposure_p50": panel.exposure.quantile(.5), "exposure_p95": panel.exposure.quantile(.95),
                           "nco_rate_p50": panel.nco_rate.quantile(.5), "npl_rate_p50": panel.npl_rate.quantile(.5),
                           "cre_share_p50": panel.loc[panel.segment.eq("CRE"), "cre_share"].quantile(.5),
                           "cre_to_tier1_p50": panel.loc[panel.segment.eq("CRE"), "cre_to_tier1"].quantile(.5)}])
    stats.to_csv(path / "sample_stats.csv", index=False)
    panel.groupby("segment").agg(banks=("bank_id", "nunique"), observations=("bank_id", "size"), exposure_mean=("exposure", "mean"),
                                 nco_rate_mean=("nco_rate", "mean"), npl_rate_mean=("npl_rate", "mean")).reset_index().to_csv(path / "segment_descriptive_stats.csv", index=False)
    series = panel.groupby(["report_date", "segment"], as_index=False).nco_rate.mean().pivot(index="report_date", columns="segment", values="nco_rate")
    macros = panel.drop_duplicates("report_date").set_index("report_date")[["unemployment_rate", "cre_price_growth", "house_price_growth", "bbb_spread"]]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    series.plot(ax=axes[0]); axes[0].set_title("Segment annualized NCO rates")
    macros.plot(ax=axes[1]); axes[1].set_title("Macro series")
    for axis in axes:
        for event in [pd.Timestamp("2008-09-30"), pd.Timestamp("2020-03-31"), pd.Timestamp("2022-03-31")]: axis.axvline(event, color="grey", alpha=.5, linestyle="--")
    fig.tight_layout(); fig.savefig(path / "time_series.png", dpi=150); plt.close(fig)
    lead_lag = []
    for segment, group in panel.groupby("segment"):
        for macro in ["unemployment_rate", "cre_price_growth", "house_price_growth", "bbb_spread"]:
            for lead in range(1, 5): lead_lag.append({"segment": segment, "macro": macro, "nco_lead_quarters": lead, "correlation": group[macro].corr(group.nco_rate.shift(-lead))})
    pd.DataFrame(lead_lag).to_csv(path / "macro_nco_lead_lag.csv", index=False)
    cre = panel[panel.segment.eq("CRE")].copy()
    pre = cre[cre.report_date.le(pd.Timestamp("2021-12-31"))].sort_values("report_date").groupby("bank_id").cre_to_tier1.last()
    cre = cre.join(pd.qcut(pre, 3, labels=["low", "middle", "high"], duplicates="drop").rename("cre_tercile"), on="bank_id")
    cre.groupby("cre_tercile", observed=True).agg(nco_rate=("nco_rate", "mean"), tier1_ratio=("tier1_ratio", "mean"), allowance_coverage=("allowance_coverage", "mean"), observations=("bank_id", "size")).reset_index().to_csv(path / "cre_terciles.csv", index=False)
