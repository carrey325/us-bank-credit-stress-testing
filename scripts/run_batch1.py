from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.config import load_config
from bankstress.io.ffiec import download_quarters
from bankstress.metadata.sample import build_institutions, update_sample_coverage
from bankstress.qa.report import write_qa
from bankstress.transform.panel import build_credit_panel
from bankstress.transform.standardize import standardize_archives


def quarter_ends(start: str, end: str) -> list[pd.Timestamp]:
    return list(pd.date_range(start, end, freq="QE"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    if args.pilot == args.full:
        parser.error("choose exactly one of --pilot or --full")
    config = load_config(ROOT)
    periods = ([pd.Timestamp(x) for x in ["2005-03-31", "2009-12-31", "2020-06-30", "2025-12-31"]] if args.pilot else quarter_ends(config["period"]["start"], config["period"]["end"]))
    manifest = download_quarters(config["paths"]["raw_ffiec"], config["paths"]["manifest"], periods)
    institutions = build_institutions(config["paths"]["metadata"], config)
    standard = standardize_archives(config["paths"]["raw_ffiec"], config["paths"]["metadata"] / "field_mapping.csv", config["paths"]["standard"], set(institutions.bank_id))
    institutions = update_sample_coverage(config["paths"]["metadata"], standard, config["sample"]["min_history_quarters"])
    lineage = pd.read_csv(config["paths"]["metadata"] / "institution_lineage.csv")
    panel = build_credit_panel(standard, institutions, config, lineage)
    config["paths"]["derived"].parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(config["paths"]["derived"], index=False)
    exception_path = config["paths"]["metadata"] / "nco_reconciliation_exceptions.csv"
    exceptions = pd.read_csv(exception_path) if exception_path.exists() else None
    write_qa(standard, panel, pd.read_csv(config["paths"]["metadata"] / "field_mapping.csv"), config["paths"]["qa"], exceptions)
    print(f"manifest rows={len(manifest)} standard rows={len(standard)} panel rows={len(panel)} banks={panel.bank_id.nunique()}")


if __name__ == "__main__":
    main()
