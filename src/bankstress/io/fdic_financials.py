"""Auditable FDIC BankFind financial-risk input for Batch 2 only."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

FDIC_FINANCIALS = "https://banks.data.fdic.gov/api/financials"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalise(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=["bank_id", "report_date", "fdic_noncurrent_loans", "fdic_total_loans", "fdic_noncurrent_ratio"])
    frame["bank_id"] = frame["CERT"].astype("Int64").astype(str)
    frame["report_date"] = pd.to_datetime(frame["REPDTE"], format="%Y%m%d")
    frame["fdic_noncurrent_loans"] = pd.to_numeric(frame["NCLNLS"], errors="coerce")
    frame["fdic_total_loans"] = pd.to_numeric(frame["LNLSNET"], errors="coerce")
    frame["fdic_noncurrent_ratio"] = frame["fdic_noncurrent_loans"] / frame["fdic_total_loans"].where(frame["fdic_total_loans"] > 0)
    return frame[["bank_id", "report_date", "fdic_noncurrent_loans", "fdic_total_loans", "fdic_noncurrent_ratio"]].drop_duplicates(["bank_id", "report_date"])


def download_noncurrent_panel(root: Path, certs: pd.Series, start: str = "2005-01-01", end: str = "2025-12-31", session: requests.sessions.Session | None = None) -> pd.DataFrame:
    """Download historical FDIC noncurrent loans and denominator by certificate.

    `NCLNLS / LNLSNET` is a bank-level ratio from a single FDIC financial record;
    it is deliberately not divided by a loan-segment exposure.
    """
    client = session or requests.Session()
    cache_dir = root / "data" / "raw" / "fdic_noncurrent"
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    manifest: list[dict] = []
    for cert in sorted({str(value) for value in certs.dropna()}):
        cache = cache_dir / f"financials_{cert}.json"
        if cache.exists():
            payload = cache.read_text(encoding="utf-8")
            downloaded_at = datetime.fromtimestamp(cache.stat().st_mtime, UTC).isoformat()
        else:
            params = {"filters": f"CERT:{cert} AND REPDTE:[{pd.Timestamp(start):%Y%m%d} TO {pd.Timestamp(end):%Y%m%d}]",
                      "fields": "CERT,REPDTE,NCLNLS,LNLSNET", "limit": 1000, "format": "json", "sort_by": "REPDTE", "sort_order": "ASC"}
            response = client.get(FDIC_FINANCIALS, params=params, timeout=60)
            response.raise_for_status()
            payload = response.text
            cache.write_text(payload, encoding="utf-8")
            downloaded_at = datetime.now(UTC).isoformat()
        decoded = json.loads(payload)
        rows.extend(item["data"] for item in decoded.get("data", []))
        manifest.append({"cert": cert, "source_url": FDIC_FINANCIALS, "download_timestamp": downloaded_at,
                         "file_name": cache.name, "sha256": _sha256(payload), "records": len(decoded.get("data", [])),
                         "fields": "NCLNLS,LNLSNET", "definition": "FDIC noncurrent loans and leases / net loans and leases"})
    panel = _normalise(rows)
    panel.to_parquet(root / "data" / "derived" / "fdic_noncurrent_panel.parquet", index=False)
    pd.DataFrame(manifest).to_csv(root / "metadata" / "fdic_noncurrent_manifest.csv", index=False)
    return panel
