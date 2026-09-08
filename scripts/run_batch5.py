from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.reporting import run_batch5


if __name__ == "__main__":
    result = run_batch5(ROOT)
    print(f"stress_universe_banks={result['summary']['stress_universe_banks']}")
    print(f"formal_model_segment_pairs={','.join(result['summary']['formal_model_segment_pairs'])}")
    print(f"audit={result['audit']['status']}")
    print(f"report={result['report_path']}")
