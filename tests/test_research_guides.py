"""Check parsing and execution boundaries introduced by the offline guides."""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def audit_root(tmp_path):
    audit = pd.read_csv(ROOT / "metadata/manual_source_audit.csv", dtype={"bank_id": str})
    row = audit.loc[(audit.bank_id == "12311") & (audit.report_date == "2007-12-31") & (audit.segment == "CRE")]
    (tmp_path / "metadata").mkdir()
    row.to_csv(tmp_path / "metadata/manual_source_audit.csv", index=False)
    return tmp_path


def test_audit_parser_preserves_recorded_inputs_and_hand_checked_flows(audit_root):
    from bankstress.research_guides import audit_flow_inputs
    from bankstress.transform.flows import quarterize_ytd

    rows = audit_flow_inputs(audit_root, "12311", "2007-12-31", "CRE")
    assert "form" not in rows
    assert len(rows) == 12
    co = rows.loc[rows.raw_code.eq("RIAD3582")].sort_values("report_date")
    assert co.numeric_value.tolist() == [14293, 23658]
    assert co.report_date.tolist() == list(pd.to_datetime(["2007-09-30", "2007-12-31"]))
    quarterized = quarterize_ytd(rows)
    q4 = quarterized.loc[quarterized.report_date.eq(pd.Timestamp("2007-12-31"))]
    totals = q4.groupby("standard_metric").quarterly_value.sum()
    assert totals.to_dict() == {"charge_off": 32326.0, "recovery": 367.0}
    assert totals.charge_off - totals.recovery == 31959.0
    assert rows.evidence_label.eq("Recorded source-audit excerpt").all()


@pytest.mark.parametrize("field,old,new", [
    ("charge_off_raw_fields_and_values", "current_ytd=23658", "current_missing=23658"),
    ("charge_off_raw_fields_and_values", "prior_ytd=14293", "prior_ytd=nan"),
    ("charge_off_raw_fields_and_values", "RIAD3590", "RIAD3582"),
    ("raw_source_files", "09302007", "06302007"),
    ("source_archive_members", "09302007.txt", "06302007.txt"),
])
def test_audit_parser_rejects_incomplete_ambiguous_or_wrong_quarter_values(audit_root, field, old, new):
    from bankstress.research_guides import audit_flow_inputs

    path = audit_root / "metadata/manual_source_audit.csv"
    audit = pd.read_csv(path, dtype=str)
    audit[field] = audit[field].str.replace(old, new, regex=False)
    audit.to_csv(path, index=False)
    with pytest.raises(ValueError, match=rf"12311.*{field}"):
        audit_flow_inputs(audit_root, "12311", "2007-12-31", "CRE")


def test_audit_parser_rejects_duplicate_or_missing_keys(audit_root):
    from bankstress.research_guides import audit_flow_inputs

    with pytest.raises(ValueError, match="WRONG_BANK"):
        audit_flow_inputs(audit_root, "WRONG_BANK", "2007-12-31", "CRE")
    path = audit_root / "metadata/manual_source_audit.csv"
    audit = pd.read_csv(path, dtype=str)
    pd.concat([audit, audit]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="12311.*exactly one"):
        audit_flow_inputs(audit_root, "12311", "2007-12-31", "CRE")


def test_audit_parser_rejects_missing_zero_quarterly_component(audit_root):
    from bankstress.research_guides import audit_flow_inputs

    path = audit_root / "metadata/manual_source_audit.csv"
    audit = pd.read_csv(path, dtype=str)
    audit["recovery_raw_fields_and_values"] = audit.recovery_raw_fields_and_values.str.replace(
        "RIAD3583: current_ytd=1; prior_ytd=1; quarterly=0 | ", "", regex=False,
    )
    audit.to_csv(path, index=False)
    with pytest.raises(ValueError, match="12311.*recovery_raw_fields_and_values.*RIAD3583"):
        audit_flow_inputs(audit_root, "12311", "2007-12-31", "CRE")


def test_root_location_accepts_both_launch_directories_and_rejects_unrelated(tmp_path):
    from bankstress.research_guides import repository_root

    assert repository_root(ROOT) == ROOT
    assert repository_root(ROOT / "notebooks") == ROOT
    with pytest.raises(FileNotFoundError, match="repository"):
        repository_root(Path(ROOT.anchor))


def _runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("guide_runner", ROOT / "scripts/check_research_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guide_repo(tmp_path):
    nb = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    runner = _runner()
    for folder in (*runner.PROTECTED, "notebooks", "src", "outputs"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "outputs/private.txt").write_text("must not be copied")
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "results/marker.txt").write_text("unchanged")
    for name in runner.GUIDES:
        notebook = nb.v4.new_notebook(cells=[nb.v4.new_code_cell(
            "from pathlib import Path\n"
            "assert 'previous_kernel' not in globals()\nprevious_kernel = 1\n"
            "root = Path.cwd() if Path.cwd().name != 'notebooks' else Path.cwd().parent\n"
            "assert not (root / 'outputs').exists()\nprint('isolated')"
        )])
        nb.write(notebook, tmp_path / "notebooks" / name)
    return tmp_path, runner


@pytest.mark.parametrize("cwd", ["root", "notebooks"])
def test_runner_uses_fresh_kernels_and_only_writes_on_request(guide_repo, cwd):
    import nbformat
    root, runner = guide_repo
    before = {p: p.read_bytes() for p in (root / "notebooks").glob("*.ipynb")}
    runner.run_guides(root, cwd=cwd, write=False)
    assert all(p.read_bytes() == content for p, content in before.items())
    runner.run_guides(root, cwd=cwd, write=True)
    for path in before:
        cell = nbformat.read(path, as_version=4).cells[0]
        assert cell.execution_count == 1
        assert cell.outputs[0].text == "isolated\n"
    assert (root / "results/marker.txt").read_text() == "unchanged"


def test_runner_error_leaves_all_original_notebooks_unchanged(guide_repo):
    import nbformat
    from nbclient.exceptions import CellExecutionError
    root, runner = guide_repo
    last = root / "notebooks" / runner.GUIDES[-1]
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("raise ValueError('deliberate')")]), last)
    before = {p: p.read_bytes() for p in (root / "notebooks").glob("*.ipynb")}
    with pytest.raises(CellExecutionError, match="deliberate"):
        runner.run_guides(root, write=True)
    assert all(p.read_bytes() == content for p, content in before.items())


def test_runner_rejects_protected_input_mutation_without_touching_source(guide_repo):
    import nbformat
    root, runner = guide_repo
    first = root / "notebooks" / runner.GUIDES[0]
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(
        "from pathlib import Path\nPath('results/marker.txt').write_text('changed')"
    )]), first)
    with pytest.raises(RuntimeError, match="protected"):
        runner.run_guides(root, write=True)
    assert (root / "results/marker.txt").read_text() == "unchanged"
