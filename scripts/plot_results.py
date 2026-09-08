"""Render the portfolio figure from committed evidence, without model refitting."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    evidence = ROOT / "results/evidence"
    tail = pd.read_csv(evidence / "tail_metrics.csv")
    tail = tail[tail.tau.eq(0.9) & tail.prediction_version.eq("POST_REARRANGEMENT")]
    scores = tail.pivot(index=["window", "segment"], columns="model_family", values="pinball_loss")
    scores["gain"] = 100 * (1 - scores.dynamic_quantile / scores.ar_quantile)
    stress = pd.read_csv(evidence / "stress_by_bank.csv")
    stress = stress[stress.segment.eq("CI") & stress.scenario.isin(["baseline", "severely_adverse"])]
    totals = stress.groupby(["model", "scenario"]).cumulative_loss_thousands.sum() / 1_000_000
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 5.8), gridspec_kw={"width_ratios": [1.2, 1]})
    fig.patch.set_facecolor("#fcfcfa")
    for axis in (left, right):
        axis.set_facecolor("#fcfcfa")
        axis.set_axisbelow(True)
        axis.grid(axis="x", alpha=0.15)
    colors = {"CRE": "#126b72", "CI": "#aa642c"}
    windows = [1, 2, 3, 4, 0]
    labels = ["2012–2016", "2017–2019", "2020–2021", "2022–2025", "Pooled OOS"]
    y = np.arange(len(windows))
    for segment, offset in [("CRE", -0.12), ("CI", 0.12)]:
        values = [scores.loc[(window, segment), "gain"] for window in windows]
        left.scatter(values, y + offset, color=colors[segment], s=55, label="C&I" if segment == "CI" else segment, zorder=3)
        for position, value in zip(y + offset, values):
            left.annotate(f"{value:+.2f}%", (value, position), xytext=(6, 0),
                          textcoords="offset points", va="center", fontsize=9, color=colors[segment])
    left.axvline(0, color="#727b83", linewidth=1)
    left.set_yticks(y, labels)
    left.invert_yaxis()
    left.set_xlim(-9, 15)
    left.set_xlabel("Q90 pinball loss reduction vs AR quantile (%)")
    left.set_title("Tail prediction | one quarter ahead", loc="left", fontweight="bold", pad=18)
    left.legend(loc="lower right", frameon=False)
    models = ["ar_mean", "dynamic_fe"]
    for scenario, offset, color, label in [
        ("baseline", -0.18, "#8ea5b4", "Baseline"),
        ("severely_adverse", 0.18, "#174765", "Severely adverse"),
    ]:
        values = [totals.loc[(model, scenario)] for model in models]
        right.barh(np.arange(2) + offset, values, height=0.30, color=color, label=label)
        for position, value in zip(np.arange(2) + offset, values):
            right.text(value + 0.18, position, f"{value:.3f}", va="center", fontsize=9)
    right.set_yticks([0, 1], ["AR mean", "Dynamic FE\nlimited challenger"])
    right.invert_yaxis()
    right.set_xlim(0, 14.7)
    right.set_xlabel("Cumulative C&I loss (USD billions)")
    right.set_title("C&I scenarios | nine quarters", loc="left", fontweight="bold", pad=18)
    right.legend(loc="center right", frameon=False)
    fig.suptitle("US Bank Credit Stress Testing",
                 x=0.06, y=0.98, ha="left", fontsize=15, fontweight="bold", color="#163444")
    fig.text(0.06, 0.06, "Left: common OOS samples, both models after quantile rearrangement. Positive values indicate lower error.\n"
             "Right: 31 banks, static 2025Q4 exposures, 2026Q1–2028Q1. AR has no macro-scenario predictors.",
             fontsize=9, color="#525d64", va="bottom")
    fig.subplots_adjust(left=0.11, right=0.96, top=0.83, bottom=0.24, wspace=0.62)
    output = ROOT / "results/figures/research_summary.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
