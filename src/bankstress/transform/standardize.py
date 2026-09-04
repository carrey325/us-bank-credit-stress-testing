from __future__ import annotations

import io
import re
from pathlib import Path
from zipfile import ZipFile

import pandas as pd


def _parse_call_report_numeric(values: pd.Series) -> pd.Series:
    """Parse CDR numeric cells, normalizing percent-formatted ratios to decimals."""
    text = values.astype("string").str.strip()
    percent = text.str.endswith("%", na=False)
    numeric = pd.to_numeric(text.str.replace(",", "", regex=False).str.rstrip("%"), errors="coerce")
    numeric.loc[percent] = numeric.loc[percent] / 100.0
    return numeric


def _report_date(path: Path) -> pd.Timestamp:
    match = re.search(r"(\d{8})\.zip$", path.name)
    if not match:
        raise ValueError(f"Cannot infer report date from {path.name}")
    return pd.to_datetime(match.group(1), format="%m%d%Y")


def standardize_archives(raw_dir: Path, mapping_path: Path, output_path: Path, bank_ids: set[str] | None = None) -> pd.DataFrame:
    mapping = pd.read_csv(mapping_path, parse_dates=["start_date", "end_date"])
    code_set = set(mapping.raw_code)
    rows: list[pd.DataFrame] = []
    for archive in sorted(raw_dir.glob("*.zip")):
        report_date = _report_date(archive)
        with ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.lower().endswith(".txt") or "readme" in name.lower():
                    continue
                content = bundle.read(name).decode("latin1")
                header = content.splitlines()[0].replace('"', '').split("\t")
                selected = [column for column in header if column in code_set]
                if not selected or "IDRSSD" not in header:
                    continue
                data = pd.read_csv(io.StringIO(content), sep="\t", dtype=str, skiprows=[1], usecols=lambda col: col.replace('"', '') in {"IDRSSD", *selected})
                data.columns = [column.replace('"', '') for column in data.columns]
                data["bank_id"] = data["IDRSSD"].astype("Int64").astype(str)
                data = data[data["bank_id"].notna()]
                if bank_ids is not None:
                    data = data[data["bank_id"].isin(bank_ids)]
                if data.empty:
                    continue
                long = data.melt(id_vars="bank_id", value_vars=selected, var_name="raw_code", value_name="raw_value")
                long["numeric_value"] = _parse_call_report_numeric(long["raw_value"])
                long = long.dropna(subset=["numeric_value"])
                applicable = mapping[(mapping.start_date <= report_date) & (mapping.end_date >= report_date)]
                long = long.merge(applicable, on="raw_code", how="inner", validate="many_to_many")
                if long.empty:
                    continue
                long["report_date"] = report_date
                long["source_file"] = archive.name
                long["source_version"] = 1
                long["mapping_version"] = "batch1-v2"
                long["form"] = long["form"].fillna("unknown")
                rows.append(long[["bank_id", "report_date", "form", "raw_code", "standard_metric", "segment", "raw_value", "numeric_value", "unit", "source_file", "source_version", "mapping_version", "stock_flow", "ytd_flag", "formula_group"]])
    if not rows:
        raise RuntimeError("No mapped Call Report values found; retain raw files and inspect mapping coverage")
    output = pd.concat(rows, ignore_index=True)
    key = ["bank_id", "report_date", "raw_code"]
    duplicated = output[output.duplicated(key, keep=False)]
    conflicts = duplicated.groupby(key, dropna=False).numeric_value.nunique()
    if (conflicts > 1).any():
        raise ValueError("Conflicting bank-date-raw-code values across Call Report schedules")
    # Some FFIEC files repeat an identical MDRM item in related schedules.  Retain one
    # observation after explicitly verifying that the duplicated values agree.
    output = output.drop_duplicates(key, keep="first")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False)
    return output
