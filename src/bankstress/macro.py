"""FRED/ALFRED macro acquisition with explicit real-time fallback labeling."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yaml

FRED_GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
ALFRED_GRAPH = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series_id}&vintage_date={vintage_date}"
RELEASE_COLUMNS = ["series_id", "observation_date", "release_date", "vintage_date", "value", "frequency", "aggregation_rule", "transformation", "source"]


def load_macro_config(root: Path) -> dict:
    with (root / "configs" / "macro_series.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _read_graph_csv(url: str, session: requests.sessions.Session | None = None) -> pd.DataFrame:
    client = session or requests.Session()
    response = client.get(url, timeout=60)
    response.raise_for_status()
    data = pd.read_csv(StringIO(response.text))
    if data.empty or "observation_date" not in data.columns:
        raise RuntimeError(f"FRED/ALFRED response had no observation_date: {url}")
    value_columns = [col for col in data.columns if col != "observation_date"]
    if len(value_columns) != 1:
        raise RuntimeError(f"Unexpected FRED/ALFRED columns: {data.columns.tolist()}")
    return data.rename(columns={value_columns[0]: "value"}).assign(
        observation_date=lambda frame: pd.to_datetime(frame["observation_date"]),
        value=lambda frame: pd.to_numeric(frame["value"], errors="coerce"),
    ).dropna(subset=["value"])


def _cache_path(cache_dir: Path, series_id: str, vintage_date: pd.Timestamp | None) -> Path:
    suffix = "final" if vintage_date is None else vintage_date.strftime("%Y%m%d")
    return cache_dir / f"{series_id}_{suffix}.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_download_manifest(root: Path, config: dict) -> None:
    """Make cached macro-source provenance as auditable as the FFIEC manifest."""
    cache_dir = root / config["cache_dir"]
    by_id = {item["series_id"]: item for item in config["series"].values()}
    rows: list[dict] = []
    for path in sorted(cache_dir.glob("*.csv")):
        series_id, suffix = path.stem.rsplit("_", maxsplit=1)
        definition = by_id.get(series_id)
        if definition is None:
            continue
        vintage = None if suffix == "final" else pd.to_datetime(suffix, format="%Y%m%d")
        rows.append({"series_id": series_id, "file_name": path.name, "source_url":
                     FRED_GRAPH.format(series_id=series_id) if vintage is None else ALFRED_GRAPH.format(series_id=series_id, vintage_date=vintage.strftime("%Y-%m-%d")),
                     "download_timestamp_utc": pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat(),
                     "vintage_date": "final" if vintage is None else vintage.date().isoformat(), "sha256": _sha256(path),
                     "source": definition["source"]})
    pd.DataFrame(rows).to_csv(root / "metadata" / "macro_download_manifest.csv", index=False)


def _download_series(cache_dir: Path, series_id: str, vintage_date: pd.Timestamp | None, session: requests.sessions.Session | None = None) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, series_id, vintage_date)
    if path.exists():
        data = pd.read_csv(path, parse_dates=["observation_date"])
        return data
    url = (ALFRED_GRAPH.format(series_id=series_id, vintage_date=vintage_date.strftime("%Y-%m-%d"))
           if vintage_date is not None else FRED_GRAPH.format(series_id=series_id))
    data = _read_graph_csv(url, session)
    data.to_csv(path, index=False)
    return data


def _quarterly(values: pd.DataFrame, rule: str, transformation: str) -> pd.DataFrame:
    out = values.copy().set_index("observation_date").sort_index()
    if rule == "quarterly_mean":
        out = out.resample("QE").mean()
    elif rule == "quarter_end":
        out = out.resample("QE").last()
    else:
        raise ValueError(f"Unsupported aggregation rule: {rule}")
    if transformation == "qoq_pct_change":
        out["value"] = out["value"].pct_change(fill_method=None) * 100
    elif transformation != "level":
        raise ValueError(f"Unsupported transformation: {transformation}")
    return out.reset_index().rename(columns={"observation_date": "report_date"})


def _vintage_at_origins(cache_dir: Path, definition: dict, origins: pd.DatetimeIndex, session: requests.sessions.Session | None) -> tuple[pd.DataFrame, list[dict]]:
    rows: list[dict] = []
    releases: list[dict] = []
    for origin in origins:
        source = _download_series(cache_dir, definition["series_id"], origin, session)
        known = source[source["observation_date"] <= origin]
        quarterly = _quarterly(known, definition["aggregation_rule"], definition["transformation"]).dropna()
        if quarterly.empty:
            continue
        record = quarterly.iloc[-1]
        rows.append({"report_date": origin, definition["output_column"]: record["value"]})
        releases.append({"series_id": definition["series_id"], "observation_date": record["report_date"],
                         "release_date": origin, "vintage_date": origin, "value": record["value"],
                         "frequency": definition["frequency"], "aggregation_rule": definition["aggregation_rule"],
                         "transformation": definition["transformation"], "source": "ALFRED vintage graph"})
    return pd.DataFrame(rows), releases


def build_macro_panel(root: Path, report_dates: pd.Series, session: requests.sessions.Session | None = None) -> pd.DataFrame:
    """Create one leak-safe macro row per panel quarter plus a release-calendar audit.

    GDP and unemployment use an ALFRED snapshot at each forecast origin.  The remaining
    series deliberately use final FRED vintage shifted one full quarter and are explicitly
    marked as a fallback in both configuration and metadata.
    """
    config = load_macro_config(root)
    cache_dir = root / config["cache_dir"]
    origins = pd.DatetimeIndex(pd.to_datetime(report_dates).drop_duplicates().sort_values())
    panel = pd.DataFrame({"report_date": origins})
    final_panel = panel.copy()
    derived_dir = root / "data" / "derived"
    derived_dir.mkdir(parents=True, exist_ok=True)
    release_rows: list[dict] = []
    for _, definition in config["series"].items():
        final_values = _download_series(cache_dir, definition["series_id"], None, session)
        final_quarterly = _quarterly(final_values, definition["aggregation_rule"], definition["transformation"])
        final = final_quarterly.rename(columns={"value": definition["output_column"]})[["report_date", definition["output_column"]]]
        final_panel = final_panel.merge(final, on="report_date", how="left")
        if definition["availability"] == "vintage":
            vintage, releases = _vintage_at_origins(cache_dir, definition, origins, session)
            panel = panel.merge(vintage, on="report_date", how="left")
            release_rows.extend(releases)
        else:
            safe = final.copy()
            safe[definition["output_column"]] = safe[definition["output_column"]].shift(1)
            panel = panel.merge(safe, on="report_date", how="left")
            # The final-vintage download extends beyond the bank-panel horizon;
            # retain those values in the final-vintage file but never place them
            # in the release-calendar audit for this run.
            audit_safe = safe[safe["report_date"].isin(origins)]
            for item in audit_safe.dropna(subset=[definition["output_column"]]).itertuples(index=False):
                release_rows.append({"series_id": definition["series_id"], "observation_date": item.report_date - pd.offsets.QuarterEnd(),
                                     "release_date": item.report_date - pd.offsets.QuarterEnd(), "vintage_date": pd.NaT,
                                     "value": getattr(item, definition["output_column"]), "frequency": definition["frequency"],
                                     "aggregation_rule": f"{definition['aggregation_rule']}; lag 1 quarter", "transformation": definition["transformation"],
                                     "source": "FRED final vintage fallback"})
    panel["macro_availability_policy"] = config["vintage_policy"]
    panel.to_parquet(derived_dir / "macro_panel.parquet", index=False)
    final_panel.to_parquet(derived_dir / "macro_panel_final.parquet", index=False)
    calendar = pd.DataFrame(release_rows, columns=RELEASE_COLUMNS).sort_values(["series_id", "release_date", "observation_date"])
    calendar.to_csv(root / "metadata" / "macro_release_calendar.csv", index=False)
    _write_download_manifest(root, config)
    note = root / "metadata" / "macro_vintage_limitation.md"
    note.write_text("# Macro vintage limitation\n\nGDP and unemployment use ALFRED snapshots at each quarter-end forecast origin. The release-calendar `release_date` field for these series is the snapshot availability date, not a separately sourced first-publication date; ALFRED proves the value was visible at that origin but this pipeline does not claim a complete release-calendar feed. CRE price, house price, BBB spread, short rate, and mortgage rate use final FRED vintages lagged one complete quarter because a release-calendar API feed was not available. These fallback variables are labeled in `macro_release_calendar.csv` and must not be described as real-time vintages.\n", encoding="utf-8")
    validate_release_calendar(calendar, origins)
    return panel


def validate_release_calendar(calendar: pd.DataFrame, origins: pd.DatetimeIndex) -> None:
    """Reject macro values whose source observation or stated availability is future-dated."""
    if calendar.empty:
        raise ValueError("Macro release calendar is empty")
    dates = pd.to_datetime(calendar["release_date"])
    observations = pd.to_datetime(calendar["observation_date"])
    if (dates > origins.max()).any() or (observations > dates).any():
        raise ValueError("Macro release calendar contains future-dated availability")
