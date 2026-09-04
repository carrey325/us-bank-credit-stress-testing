from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.reporting import run_batch5


if __name__ == "__main__":
    result = run_batch5(ROOT)
    print(f"conformal_rows={len(result['metrics'])}")
    print(f"audit={result['audit']['status']}")
    print(f"report={result['report_path']}")
