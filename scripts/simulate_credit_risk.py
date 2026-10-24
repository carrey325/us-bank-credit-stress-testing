"""Simulate conditional nine-quarter C&I losses using a verified frozen run."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bankstress.modelrisk.workflow import load_settings
from bankstress.modelrisk.stochastic_workflow import run_stochastic

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--paths', type=int)
    parser.add_argument('--output-name', default='stochastic')
    args = parser.parse_args()
    print(run_stochastic(ROOT, args.run, load_settings(ROOT, args.config), args.paths, args.output_name))
