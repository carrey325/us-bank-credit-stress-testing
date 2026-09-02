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
        z.writestr("FFIEC CDR Call Schedule RCCI 03312025.txt", '"IDRSSD"\tRCON1766\nDESCRIPTION\tDESCRIPTION\n1\t\n2\t20\n')
    mapping = tmp_path / "mapping.csv"
    pd.DataFrame([{"raw_code":"RCON1766", "standard_metric":"exposure", "segment":"CI", "schedule":"RC-C", "form":"041", "start_date":"2005-03-31", "end_date":"2025-12-31", "stock_flow":"stock", "ytd_flag":0, "unit":"thousands", "formula_group":"x"}]).to_csv(mapping, index=False)
    result = standardize_archives(raw, mapping, tmp_path / "standard.parquet", {"1", "2"})
    assert result.bank_id.tolist() == ["2"]
    assert result.numeric_value.tolist() == [20]
    shutil.rmtree(tmp_path)
