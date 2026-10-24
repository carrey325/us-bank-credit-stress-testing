"""Read-only teaching inputs; all financial transformations remain in their modules."""
from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from bankstress.transform.panel import required_flow_components


def repository_root(start: Path | None = None) -> Path:
    """Locate this repository from its root, notebooks, or a nested directory."""
    here = Path.cwd() if start is None else Path(start).resolve()
    for candidate in (here, *here.parents):
        if all((candidate / name).is_file() for name in (
            "pyproject.toml", "configs/model_specs.yaml", "results/summary.json",
        )):
            return candidate
    raise FileNotFoundError("Cannot locate the bankstress repository from the working directory")


def audit_flow_inputs(root: Path, bank_id: str, report_date: str, segment: str) -> pd.DataFrame:
    """Parse a complete adjacent-quarter excerpt, never infer form or balances.

    This adapter intentionally rejects unsupported or incomplete audit prose.
    Source archives are labels only: it does not open or verify those archives.
    """
    key = f"{bank_id}/{report_date}/{segment}"
    audit = pd.read_csv(Path(root) / "metadata/manual_source_audit.csv", dtype=str)
    for field in ("bank_id", "report_date", "segment"):
        if field not in audit:
            raise ValueError(f"{key}: missing {field}")
    selected = audit.loc[audit.bank_id.eq(str(bank_id)) & audit.report_date.eq(report_date) & audit.segment.eq(segment)]
    if len(selected) != 1:
        raise ValueError(f"{key}: expected exactly one audit record, found {len(selected)}")
    record = selected.iloc[0]

    def fail(field: str, reason: str) -> None:
        raise ValueError(f"{key}: {field}: {reason}")

    def text(field: str) -> str:
        value = record.get(field)
        if pd.isna(value) or not str(value).strip():
            fail(field, "missing recorded value")
        return str(value)

    date = pd.Timestamp(report_date)
    quarter = date.to_period("Q")
    if date != quarter.end_time.normalize() or date.quarter == 1:
        fail("report_date", "adapter requires a quarter end after Q1 with an adjacent YTD excerpt")
    prior = (quarter - 1).end_time.normalize()
    archives = [item.strip() for item in text("raw_source_files").split(";")]
    by_date = {}
    for archive in archives:
        token = re.fullmatch(r"FFIEC CDR Call Bulk All Schedules (\d{8})\.zip", archive)
        if not token:
            fail("raw_source_files", "unrecognized archive label")
        try:
            archived_date = pd.to_datetime(token[1], format="%m%d%Y")
        except ValueError:
            fail("raw_source_files", "invalid archive date")
        if archived_date in by_date:
            fail("raw_source_files", "ambiguous archive date")
        by_date[archived_date] = archive
    if set(by_date) != {prior, date}:
        fail("raw_source_files", "dates do not match current and adjacent prior quarters")
    members = text("source_archive_members")
    member_dates = set()
    for member in members.split(";"):
        parts = member.strip().split("::")
        if len(parts) != 2 or parts[0] not in archives:
            fail("source_archive_members", "member has no matching archive")
        archive_token = re.search(r"(\d{8})\.zip$", parts[0])[1]
        if not parts[1].endswith(f"{archive_token}.txt"):
            fail("source_archive_members", "member date differs from its archive")
        member_dates.add(archive_token)
    if member_dates != {date.strftime("%m%d%Y"), prior.strftime("%m%d%Y")}:
        fail("source_archive_members", "missing quarter lineage")

    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    pattern = re.compile(rf"([A-Z0-9]+): current_ytd=({number}); prior_ytd=({number}); quarterly=({number})")
    groups = {"CRE": ["cre_nco"], "CI": ["ci_nco_041", "ci_nco_031"],
              "Mortgage": ["mortgage_closed_end_nco"]}
    if segment not in groups:
        fail("segment", "no supported component definition")
    rows = []
    for metric in ("charge_off", "recovery"):
        field = f"{metric}_raw_fields_and_values"
        seen = set()
        for part in text(field).split("|"):
            match = pattern.fullmatch(part.strip())
            if not match or match[1] in seen:
                fail(field, "missing/invalid token or duplicate raw code")
            code, current_ytd, prior_ytd, _ = match.groups()
            seen.add(code)
            for when, value in ((prior, prior_ytd), (date, current_ytd)):
                rows.append({"bank_id": str(bank_id), "report_date": when, "segment": segment,
                             "standard_metric": metric, "raw_code": code, "numeric_value": float(value),
                             "source_file": by_date[when], "evidence_label": "Recorded source-audit excerpt"})
        # Validate complete code sets using the existing definitions. For C&I,
        # accepting either complete set does not infer or supply a filing form.
        candidates = [required_flow_components(segment, metric, date, {group}) for group in groups[segment]]
        if seen not in candidates:
            closest = min(candidates, key=lambda required: len(required.symmetric_difference(seen)))
            fail(field, f"incomplete component set; missing={sorted(closest - seen)}, unexpected={sorted(seen - closest)}")
    return pd.DataFrame(rows)


def synthetic_standard_rows() -> pd.DataFrame:
    """Construct fictional 041 rows for a complete denominator and negative NCO."""
    rows = []
    for date, exposure, charge, recovery in [
        ("2024-12-31", 1000, 8, 4), ("2025-03-31", 1200, 3, 1),
        ("2025-06-30", 1200, 4, 5),
    ]:
        for metric, code, value, flow, group in [
            ("exposure", "RCON1766", exposure, "stock", "ci_exposure"),
            ("charge_off", "RIAD4638", charge, "flow", "ci_nco_041"),
            ("recovery", "RIAD4608", recovery, "flow", "ci_nco_041"),
            ("total_loans", "RCON2122", 2000, "stock", "bank_control"),
        ]:
            rows.append({"bank_id": "DEMO_CI", "report_date": pd.Timestamp(date), "form": "041",
                         "segment": "All" if metric == "total_loans" else "CI", "standard_metric": metric,
                         "raw_code": code, "numeric_value": value, "stock_flow": flow,
                         "ytd_flag": int(flow == "flow"), "formula_group": group, "unit": "thousands",
                         "source_file": "Synthetic demonstration"})
    return pd.DataFrame(rows)


def synthetic_ci_inputs():
    """Supply synthetic parameters to the existing prediction interface; no fit."""
    import numpy as np
    from bankstress.stress import StressFit

    jump = pd.DataFrame([{"bank_id": "DEMO_CI", "bank_name": "Synthetic demonstration bank",
                          "segment": "CI", "nco_rate": 0.02, "exposure": 1000.0,
                          "tier1_capital": 100.0, "allowance": 20.0, "total_loans": 2000.0,
                          "npl_rate": 0.03}])
    terms = ["lagged_nco_rate", "lagged_noncurrent_ratio", "lagged_gdp_growth"]
    fit = {"predictors": terms, "beta": np.array([0.5, 0.1, -0.002]),
           "entity_means": pd.DataFrame([{**dict.fromkeys(terms, 0.0), "nco_rate": 0.001}], index=["DEMO_CI::CI"])}
    model = StressFit("synthetic_dynamic_fe", "fe", {"CI": fit}, {"CI": terms})
    quarters = pd.period_range("2026Q1", "2028Q1", freq="Q")
    scenarios = pd.DataFrame([
        {"scenario": name, "scenario_type": "Synthetic demonstration", "quarter": quarter.end_time.normalize(),
         "horizon": i + 1, "lagged_gdp_growth": growth,
         "lagged_gdp_growth_source_quarter": (quarter - 1).end_time.normalize()}
        for name, values in [("synthetic_mild", [2.0] * 9), ("synthetic_contraction", [2, -3, -3, -2, -1, 0, 1, 2, 2])]
        for i, (quarter, growth) in enumerate(zip(quarters, values, strict=True))
    ])
    return jump, scenarios, [model]
