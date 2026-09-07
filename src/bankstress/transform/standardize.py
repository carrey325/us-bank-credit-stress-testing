from __future__ import annotations

import io
import re
from pathlib import Path
from zipfile import ZipFile

import pandas as pd


STANDARD_MAPPING_VERSION = "repair-r1-v2"
POR_FORM_RAW_CODE = "POR_FINANCIAL_INSTITUTION_FILING_TYPE"


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


def _filing_metadata(bundle: ZipFile) -> pd.DataFrame:
    """Read reporter identity and actual filing form from the archive POR member."""
    por_names = [name for name in bundle.namelist() if "bulk por" in name.lower() and name.lower().endswith(".txt")]
    if len(por_names) != 1:
        raise ValueError(f"Expected one Call Report POR member, found {len(por_names)}")
    content = bundle.read(por_names[0]).decode("latin1")
    por = pd.read_csv(io.StringIO(content), sep="\t", dtype=str)
    por.columns = [column.replace('"', '') for column in por.columns]
    required = {"IDRSSD", "Financial Institution Filing Type"}
    if not required.issubset(por.columns):
        raise ValueError(f"POR member lacks required filing-form fields: {sorted(required - set(por.columns))}")
    result = pd.DataFrame({
        "bank_id": pd.to_numeric(por["IDRSSD"], errors="coerce").astype("Int64").astype(str),
        "filing_form": por["Financial Institution Filing Type"].astype("string").str.strip().str.lstrip("0"),
        "filing_bank_name": por.get("Financial Institution Name", pd.Series(pd.NA, index=por.index)).astype("string").str.strip(),
    })
    return result.loc[result["bank_id"].ne("<NA>")].drop_duplicates("bank_id")


def _filing_forms(bundle: ZipFile) -> dict[str, str]:
    """Compatibility helper returning the POR filing-form lookup."""
    metadata = _filing_metadata(bundle)
    return dict(zip(metadata["bank_id"], metadata["filing_form"]))


def _mapping_applies(mapping_form: pd.Series, filing_form: pd.Series) -> pd.Series:
    allowed = mapping_form.astype("string").str.split("/").map(
        lambda parts: {str(part).strip().lstrip("0") for part in parts}
    )
    return pd.Series(
        [str(actual).strip().lstrip("0") in parts for parts, actual in zip(allowed, filing_form.astype("string"))],
        index=mapping_form.index,
    )


def standardize_archives(raw_dir: Path, mapping_path: Path, output_path: Path, bank_ids: set[str] | None = None) -> pd.DataFrame:
    mapping = pd.read_csv(mapping_path, parse_dates=["start_date", "end_date"])
    code_set = set(mapping.raw_code)
    rows: list[pd.DataFrame] = []
    for archive in sorted(raw_dir.glob("*.zip")):
        report_date = _report_date(archive)
        with ZipFile(archive) as bundle:
            filing_metadata = _filing_metadata(bundle)
            if bank_ids is not None:
                filing_metadata = filing_metadata.loc[filing_metadata["bank_id"].isin(bank_ids)].copy()
            filing_forms = dict(zip(filing_metadata["bank_id"], filing_metadata["filing_form"]))
            filing_names = dict(zip(filing_metadata["bank_id"], filing_metadata["filing_bank_name"]))
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
                data["filing_form"] = data["bank_id"].map(filing_forms).astype("string")
                data["filing_bank_name"] = data["bank_id"].map(filing_names).astype("string")
                long = data.melt(id_vars=["bank_id", "filing_form", "filing_bank_name"], value_vars=selected, var_name="raw_code", value_name="raw_value")
                long["numeric_value"] = _parse_call_report_numeric(long["raw_value"])
                applicable = mapping[(mapping.start_date <= report_date) & (mapping.end_date >= report_date)]
                long = long.merge(applicable, on="raw_code", how="inner", validate="many_to_many")
                long = long[_mapping_applies(long["form"], long["filing_form"])]
                if long.empty:
                    continue
                long["report_date"] = report_date
                long["source_file"] = archive.name
                long["source_version"] = 1
                long["mapping_version"] = STANDARD_MAPPING_VERSION
                long["form"] = long["filing_form"]
                long["raw_presence_status"] = "PRESENT"
                long.loc[long["numeric_value"].eq(0), "raw_presence_status"] = "REPORTED_ZERO"
                long.loc[long["numeric_value"].isna(), "raw_presence_status"] = "BLANK"
                rows.append(long[["bank_id", "report_date", "form", "filing_bank_name", "raw_code", "standard_metric", "segment", "raw_value", "numeric_value", "raw_presence_status", "unit", "source_file", "source_version", "mapping_version", "stock_flow", "ytd_flag", "formula_group"]])
            # Preserve a reporter-quarter spine even when its POR form has no
            # verified segment mapping (notably FFIEC 051).  These are source
            # observations, not imputed financial values.
            if not filing_metadata.empty:
                por_rows = filing_metadata.copy()
                por_rows["report_date"] = report_date
                por_rows["form"] = por_rows["filing_form"]
                por_rows["raw_code"] = POR_FORM_RAW_CODE
                por_rows["standard_metric"] = "filing_presence"
                por_rows["segment"] = "All"
                por_rows["raw_value"] = por_rows["filing_form"]
                por_rows["numeric_value"] = 1.0
                por_rows["raw_presence_status"] = "PRESENT"
                por_rows["unit"] = "indicator"
                por_rows["source_file"] = archive.name
                por_rows["source_version"] = 1
                por_rows["mapping_version"] = STANDARD_MAPPING_VERSION
                por_rows["stock_flow"] = "stock"
                por_rows["ytd_flag"] = 0
                por_rows["formula_group"] = "filing_presence"
                rows.append(por_rows[["bank_id", "report_date", "form", "filing_bank_name", "raw_code", "standard_metric", "segment", "raw_value", "numeric_value", "raw_presence_status", "unit", "source_file", "source_version", "mapping_version", "stock_flow", "ytd_flag", "formula_group"]])
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
