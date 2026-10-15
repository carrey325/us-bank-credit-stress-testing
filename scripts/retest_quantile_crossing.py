"""Produce the independent historical quantile-crossing remediation record."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bankstress.modelrisk.workflow import remediation_run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--expected-crossings', type=int, default=507)
    args = parser.parse_args()
    print(remediation_run(args.run, args.expected_crossings))
