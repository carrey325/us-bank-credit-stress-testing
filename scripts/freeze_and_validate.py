"""Freeze archive inputs, reconstruct states, fit challengers, independently score."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bankstress.modelrisk.workflow import load_settings, validate_run
from bankstress.modelrisk.evidence import verify_run, verify_evidence, export_evidence

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--archive', type=Path, help='Archive root containing data/ and outputs/')
    mode.add_argument('--verify-run', type=Path, help='Verify and independently rescore an existing run without fitting')
    mode.add_argument('--verify-evidence', type=Path, help='Verify compact evidence hashes without local bulk data')
    mode.add_argument('--export-run', type=Path, help='Export compact evidence after verifying the full run')
    parser.add_argument('--run-id')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--stochastic', default='stochastic')
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.archive:
        if not args.run_id:
            parser.error('--archive requires --run-id')
        print(validate_run(ROOT, args.archive, args.run_id, load_settings(ROOT, args.config)))
    elif args.verify_run:
        print(verify_run(args.verify_run, args.stochastic))
    elif args.verify_evidence:
        manifest = verify_evidence(args.verify_evidence)
        print(f'Verified {len(manifest["files"])} model risk evidence files')
    else:
        if not args.destination:
            parser.error('--export-run requires --destination')
        print(export_evidence(args.export_run, args.destination, args.stochastic))
