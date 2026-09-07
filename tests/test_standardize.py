from pathlib import Path
import shutil
from zipfile import ZipFile
import pandas as pd

from bankstress.transform.standardize import standardize_archives


def test_standard_layer_preserves_missing_not_zero():
    tmp_path = Path(".test-tmp-standardize")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir()
    raw = tmp_path / "raw"; raw.mkdir()
    archive = raw / "FFIEC CDR Call Bulk All Schedules 03312025.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("FFIEC CDR Call Bulk POR 03312025.txt", '"IDRSSD"\tFinancial Institution Filing Type\n1\t041\n2\t041\n')
        z.writestr("FFIEC CDR Call Schedule RCCI 03312025.txt", '"IDRSSD"\tRCON1766\nDESCRIPTION\tDESCRIPTION\n1\t\n2\t20\n')
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([{"raw_code":"RCON1766", "standard_metric":"exposure", "segment":"CI", "schedule":"RC-C", "form":"041", "start_date":"2005-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"thousands", "formula_group":"x"}]).to_csv(mapping, index=False)
    result = standardize_archives(raw, mapping, tmp_path / "standard.parquet", {"1", "2"})
    mapped = result.loc[result["raw_code"].eq("RCON1766")].reset_index(drop=True)
    assert mapped.bank_id.tolist() == ["1", "2"]
    assert pd.isna(mapped.loc[0, "numeric_value"])
    assert mapped.loc[0, "raw_presence_status"] == "BLANK"
    assert mapped.loc[1, "numeric_value"] == 20
    assert mapped.loc[1, "raw_presence_status"] == "PRESENT"
    shutil.rmtree(tmp_path)


def test_standard_layer_normalizes_percent_suffixed_ratio_to_decimal():
    tmp_path = Path(".test-tmp-standardize-percent")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir()
    raw = tmp_path / "raw"; raw.mkdir()
    archive = raw / "FFIEC CDR Call Bulk All Schedules 03312025.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("FFIEC CDR Call Bulk POR 03312025.txt", '"IDRSSD"\tFinancial Institution Filing Type\n1\t031\n')
        z.writestr("FFIEC CDR Call Schedule RCRI 03312025.txt", '"IDRSSD"\tRCFA7206\nDESCRIPTION\tDESCRIPTION\n1\t12.3456%\n')
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([{"raw_code":"RCFA7206", "standard_metric":"tier1_risk_based_ratio", "segment":"All", "schedule":"RC-R", "form":"031", "start_date":"2014-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"decimal", "formula_group":"regulatory_capital"}]).to_csv(mapping, index=False)
    result = standardize_archives(raw, mapping, tmp_path / "standard.parquet", {"1"})
    mapped = result.loc[result["raw_code"].eq("RCFA7206")].iloc[0]
    assert mapped["raw_value"] == "12.3456%"
    assert mapped["numeric_value"] == 0.123456
    shutil.rmtree(tmp_path)


def test_standard_layer_enforces_actual_por_form_applicability():
    tmp_path = Path(".test-tmp-standardize-form")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(); raw = tmp_path / "raw"; raw.mkdir()
    archive = raw / "FFIEC CDR Call Bulk All Schedules 03312025.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("FFIEC CDR Call Bulk POR 03312025.txt", '"IDRSSD"\tFinancial Institution Filing Type\n1\t031\n2\t041\n')
        z.writestr("FFIEC CDR Call Schedule RCCI 03312025.txt", '"IDRSSD"\tRCON1766\tRCFD1763\nDESCRIPTION\tDESCRIPTION\tDESCRIPTION\n1\t99\t40\n2\t20\t\n')
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([
        {"raw_code":"RCON1766", "standard_metric":"exposure", "segment":"CI", "schedule":"RC-C", "form":"041", "start_date":"2005-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"thousands", "formula_group":"ci_exposure"},
        {"raw_code":"RCFD1763", "standard_metric":"exposure", "segment":"CI", "schedule":"RC-C", "form":"031", "start_date":"2005-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"thousands", "formula_group":"ci_exposure"},
    ]).to_csv(mapping, index=False)
    result = standardize_archives(raw, mapping, tmp_path / "standard.parquet", {"1", "2"})
    mapped = result.loc[result["raw_code"].isin({"RCFD1763", "RCON1766"})]
    assert set(zip(mapped.bank_id, mapped.raw_code, mapped.form)) == {("1", "RCFD1763", "31"), ("2", "RCON1766", "41")}
    shutil.rmtree(tmp_path)


def test_standard_layer_retains_unsupported_por_form_as_filing_spine():
    tmp_path = Path(".test-tmp-standardize-unsupported-form")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(); raw = tmp_path / "raw"; raw.mkdir()
    archive = raw / "FFIEC CDR Call Bulk All Schedules 03312020.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("FFIEC CDR Call Bulk POR 03312020.txt", '"IDRSSD"\tFinancial Institution Filing Type\tFinancial Institution Name\n962966\t051\tGOLDEN PACIFIC BANK, NATIONAL ASSOCIATION\n')
        z.writestr("FFIEC CDR Call Schedule RCCI 03312020.txt", '"IDRSSD"\tRCON1766\nDESCRIPTION\tDESCRIPTION\n962966\t16415\n')
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([{"raw_code":"RCON1766", "standard_metric":"exposure", "segment":"CI", "schedule":"RC-C", "form":"041", "start_date":"2005-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"thousands", "formula_group":"ci_exposure"}]).to_csv(mapping, index=False)
    result = standardize_archives(raw, mapping, tmp_path / "standard.parquet", {"962966"})
    assert len(result) == 1
    row = result.iloc[0]
    assert row["raw_code"] == "POR_FINANCIAL_INSTITUTION_FILING_TYPE"
    assert row["form"] == "51"
    assert row["filing_bank_name"] == "GOLDEN PACIFIC BANK, NATIONAL ASSOCIATION"
    assert row["standard_metric"] == "filing_presence"
    shutil.rmtree(tmp_path)
