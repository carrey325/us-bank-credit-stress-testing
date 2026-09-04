from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.validation import run_historical_pseudo_stress, run_unified_oos, write_validation_figures


def main() -> None:
    panel_path = ROOT / "data" / "derived" / "model_panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError(
            "Batch 3 requires data/derived/model_panel.parquet. Rebuild it through the committed Batch 1 and Batch 2 scripts; do not use synthetic research inputs."
        )
    panel = pd.read_parquet(panel_path)
    _, predictions, comparison, tail = run_unified_oos(panel, ROOT)
    stress = run_historical_pseudo_stress(panel, ROOT)
    write_validation_figures(predictions, stress, ROOT)
    diagnostics = pd.read_csv(ROOT / "outputs" / "models" / "bayesian" / "diagnostics.csv")
    bayesian_status = "posterior forecasts included" if diagnostics["status"].eq("sampled").all() else "explicit fallback; no posterior forecasts included"
    summary = ROOT / "outputs" / "validation" / "run_summary.md"
    summary.write_text(
        "# Batch 3 successful run\n\n"
        f"- Unified OOS forecasts: {len(predictions):,}\n"
        f"- Mean-metric rows: {len(comparison):,}\n"
        f"- Tail-metric rows: {len(tail):,}\n"
        f"- Recursive pseudo-stress forecasts: {len(stress):,}\n"
        f"- Bayesian status: {bayesian_status}.\n"
        "- Figures: six required OOS/pseudo-stress figures in `outputs/validation/figures/`; the Bayesian panel is explicitly labelled unavailable if fallback is active.\n"
        "- The pseudo-stress path uses realised macro history and recursive NCO; future bank controls are held at their last pre-window values.\n"
        "- `pseudo_stress_metrics.csv` reports quantile pinball loss and empirical/nominal exceedance rates alongside mean-error metrics. Recursive CRE Q0.90 paths are unstable in COVID and 2022+; they are a tail-model limitation, not full recursive-stress validation.\n",
        encoding="utf-8",
    )
    print(f"oos={len(predictions)} comparison={len(comparison)} tail={len(tail)} pseudo_stress={len(stress)}")


if __name__ == "__main__":
    main()
