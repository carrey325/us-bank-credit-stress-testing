from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from ffiec_data_collector import FFIECDownloader, FileFormat


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_quarters(raw_dir: Path, manifest_path: Path, quarters: list[pd.Timestamp]) -> pd.DataFrame:
    """Download immutable FFIEC single-period TSV archives and update the manifest.

    Existing archives are never overwritten.  A regenerated official archive therefore
    receives its own filename/version row if its digest differs.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_csv(manifest_path) if manifest_path.exists() else pd.DataFrame()
    downloader = FFIECDownloader(raw_dir)
    rows: list[dict] = []
    for period in quarters:
        known = existing[existing.get("report_period", pd.Series(dtype=str)) == period.date().isoformat()]
        if not known.empty:
            # A manifest row is an immutable snapshot.  Do not ask the remote service
            # for the same period again and risk replacing it with a regenerated file.
            rows.append(known.iloc[-1].to_dict())
            continue
        result = downloader.download_cdr_single_period(period.strftime("%Y%m%d"), FileFormat.TSV)
        if not result.success or result.file_path is None:
            raise RuntimeError(f"FFIEC download failed for {period.date()}: {result.error_message}")
        file_path = Path(result.file_path)
        checksum = sha256(file_path)
        prior = existing[(existing.get("report_period", pd.Series(dtype=str)) == period.date().isoformat()) &
                         (existing.get("sha256", pd.Series(dtype=str)) == checksum)]
        version = 1 if prior.empty else int(prior.iloc[-1]["version"])
        rows.append({
            "source_url": "https://cdr.ffiec.gov/public/pws/downloadbulkdata.aspx",
            "download_timestamp": datetime.now(UTC).isoformat(),
            "file_name": file_path.name,
            "sha256": checksum,
            "report_period": period.date().isoformat(),
            "version": version,
            "size_bytes": file_path.stat().st_size,
        })
    fresh = pd.DataFrame(rows)
    combined = pd.concat([existing, fresh], ignore_index=True).drop_duplicates(
        subset=["report_period", "sha256"], keep="last"
    ).sort_values(["report_period", "version"])
    combined.to_csv(manifest_path, index=False)
    return combined
