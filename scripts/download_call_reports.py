"""Restore ignored FFIEC archives from the committed Batch 1 manifest period range.

This is input recovery only: it reuses Batch 1's downloader and does not alter
Batch 1 logic or overwrite its tracked manifest.  The recovery manifest records
the fresh download time and SHA-256 for each retrieved archive.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.config import load_config
from bankstress.io.ffiec import download_quarters


def main() -> None:
    config = load_config(ROOT)
    periods = list(pd.date_range(config["period"]["start"], config["period"]["end"], freq="QE"))
    manifest = ROOT / "data" / "manifests" / "ffiec_recovery_manifest.csv"
    # The upstream downloader has no request timeout.  Bound only the network call
    # while retaining its download, hashing, and manifest implementation unchanged.
    original_request = requests.sessions.Session.request

    def bounded_request(session, method, url, **kwargs):
        kwargs.setdefault("timeout", 60)
        return original_request(session, method, url, **kwargs)

    requests.sessions.Session.request = bounded_request
    failures: list[dict] = []
    for period in periods:
        try:
            result = download_quarters(config["paths"]["raw_ffiec"], manifest, [period])
            print(f"recovered={period.date()} manifest_rows={len(result)}", flush=True)
        except Exception as error:
            failures.append({"report_period": period.date().isoformat(), "error_type": type(error).__name__, "error": str(error)})
            print(f"failed={period.date()} error={type(error).__name__}: {error}", flush=True)
    if failures:
        pd.DataFrame(failures).to_csv(ROOT / "metadata" / "ffiec_recovery_failures.csv", index=False)
        raise RuntimeError(f"FFIEC recovery incomplete: {len(failures)} quarter(s) failed; see metadata/ffiec_recovery_failures.csv")
    print(f"recovery complete: {len(periods)} periods; manifest={manifest}")


if __name__ == "__main__":
    main()
