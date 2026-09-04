from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.stress import run_batch4


if __name__ == "__main__":
    result = run_batch4(ROOT)
    summary = result["summary"]
    for scenario in ("baseline", "severely_adverse"):
        value = summary[(summary.scenario == scenario) & (summary.model == "dynamic_fe")].cumulative_loss.sum()
        print(f"{scenario}_aggregate_loss={value:.2f}")
    print(f"stress_universe_banks={result['metrics']['n_banks']}")
