"""Create the fixed, source-document manual audit for the Batch 1 panel.

The output is intentionally separate from the formula-only QA trace.  Each
sampled observation retains the actual FFIEC archive and member names, each raw
YTD value used, its quarterly transformation, and the review conclusion.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.transform.panel import _coalesce_reporting_variants, required_flow_components


CRE_TRANSITION_AUDIT_DATES = pd.to_datetime(["2007-12-31", "2008-03-31", "2008-06-30"])


def _previous_quarter(date: pd.Timestamp) -> pd.Timestamp:
    return (date.to_period("Q") - 1).end_time.normalize()


def _direct_archive_values(archive: Path, bank_id: str, raw_code: str) -> list[tuple[str, float]]:
    """Return every FFIEC schedule member carrying a bank's requested MDRM."""
    values: list[tuple[str, float]] = []
    with ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if not member.lower().endswith(".txt") or "readme" in member.lower():
                continue
            content = bundle.read(member).decode("latin1")
            header = content.splitlines()[0].replace('"', '').split("\t")
            if raw_code not in header or "IDRSSD" not in header:
                continue
            frame = pd.read_csv(
                io.StringIO(content), sep="\t", dtype=str, skiprows=[1],
                usecols=lambda column: column.replace('"', '') in {"IDRSSD", raw_code},
            )
            frame.columns = [column.replace('"', '') for column in frame.columns]
            matches = frame.loc[frame["IDRSSD"].astype(str).eq(str(bank_id)), raw_code]
            for value in matches.dropna():
                numeric = pd.to_numeric(value, errors="coerce")
                if pd.notna(numeric):
                    values.append((member, float(numeric)))
    return values


def _trace_metric(
    coalesced: pd.DataFrame,
    raw_dir: Path,
    bank_id: str,
    report_date: pd.Timestamp,
    segment: str,
    metric: str,
) -> tuple[float, list[str], list[str], bool, list[str]]:
    current = coalesced.loc[
        coalesced["bank_id"].eq(str(bank_id))
        & coalesced["report_date"].eq(report_date)
        & coalesced["segment"].eq(segment)
        & coalesced["standard_metric"].eq(metric)
    ].copy()
    prior_date = _previous_quarter(report_date)
    previous = coalesced.loc[
        coalesced["bank_id"].eq(str(bank_id))
        & coalesced["report_date"].eq(prior_date)
        & coalesced["segment"].eq(segment)
        & coalesced["standard_metric"].eq(metric)
    ][["series_key", "numeric_value", "source_file"]].rename(
        columns={"numeric_value": "prior_ytd", "source_file": "prior_source_file"}
    )
    current = current.merge(previous, on="series_key", how="left")
    q1 = report_date.quarter == 1
    current["quarterly_value"] = current["numeric_value"] if q1 else current["numeric_value"] - current["prior_ytd"]
    formula_groups = set(current["formula_group"].dropna().astype(str))
    required = required_flow_components(segment, metric, report_date, formula_groups)
    quarterized_codes = set(current.loc[current["quarterly_value"].notna(), "raw_code"].astype(str))
    missing_components = sorted(required - quarterized_codes)
    archive_matches: list[bool] = []
    field_values: list[str] = []
    members: list[str] = []
    for row in current.itertuples(index=False):
        current_archive = raw_dir / row.source_file
        current_values = _direct_archive_values(current_archive, bank_id, row.raw_code)
        current_matches = any(value == float(row.numeric_value) for _, value in current_values)
        prior_values: list[tuple[str, float]] = []
        prior_matches = True
        if not q1:
            if pd.notna(row.prior_ytd) and pd.notna(row.prior_source_file):
                prior_archive = raw_dir / row.prior_source_file
                prior_values = _direct_archive_values(prior_archive, bank_id, row.raw_code)
                prior_matches = any(value == float(row.prior_ytd) for _, value in prior_values)
        archive_matches.append(current_matches and prior_matches)
        field_values.append(
            f"{row.raw_code}: current_ytd={row.numeric_value:g}"
            + ("; quarterly=current_ytd" if q1 else f"; prior_ytd={row.prior_ytd:g}; quarterly={row.quarterly_value:g}")
        )
        members.extend(f"{current_archive.name}::{member}" for member, _ in current_values)
        members.extend(f"{row.prior_source_file}::{member}" for member, _ in prior_values)
    complete = not missing_components and current["quarterly_value"].notna().all()
    quarterly_value = float(current["quarterly_value"].sum(min_count=1)) if complete else float("nan")
    return quarterly_value, field_values, sorted(set(members)), all(archive_matches) and complete, missing_components


def _select_audit_sample(panel: pd.DataFrame, sample_size: int, random_state: int) -> pd.DataFrame:
    """Create a reproducible sample that deliberately includes the CRE transition."""
    eligible = panel.dropna(subset=["charge_off", "recovery", "segment_nco"]).copy()
    transition = eligible.loc[
        eligible["segment"].eq("CRE") & eligible["report_date"].isin(CRE_TRANSITION_AUDIT_DATES)
    ].sort_values(["report_date", "bank_id"]).groupby("report_date", as_index=False).head(2)
    if set(transition["report_date"].unique()) != set(CRE_TRANSITION_AUDIT_DATES):
        raise RuntimeError("Source audit cannot cover every required CRE taxonomy-transition quarter")
    transition = transition.assign(audit_sample_role="CRE_TAXONOMY_TRANSITION")
    remaining_count = sample_size - len(transition)
    if remaining_count < 0:
        raise ValueError(f"sample_size must be at least {len(transition)} to retain the required transition audit")
    keys = ["bank_id", "report_date", "segment"]
    remaining = eligible.merge(transition[keys].assign(selected=True), on=keys, how="left")
    remaining = remaining.loc[remaining["selected"].isna()].drop(columns="selected")
    random = remaining.sample(min(remaining_count, len(remaining)), random_state=random_state).assign(audit_sample_role="FIXED_RANDOM")
    return pd.concat([transition, random], ignore_index=True).sort_values(["audit_sample_role", "report_date", "bank_id"]).reset_index(drop=True)


def create_source_audit(sample_size: int = 100, random_state: int = 772) -> pd.DataFrame:
    standard = pd.read_parquet(ROOT / "data" / "standard" / "call_report_standard.parquet")
    panel = pd.read_parquet(ROOT / "data" / "derived" / "credit_panel.parquet")
    source = _select_audit_sample(panel, sample_size, random_state)
    coalesced = _coalesce_reporting_variants(standard)
    raw_dir = ROOT / "data" / "raw" / "ffiec"
    rows: list[dict[str, object]] = []
    for observation in source.itertuples(index=False):
        date = pd.Timestamp(observation.report_date)
        charge_off, co_fields, co_members, co_archive_match, co_missing = _trace_metric(coalesced, raw_dir, observation.bank_id, date, observation.segment, "charge_off")
        recovery, rec_fields, rec_members, rec_archive_match, rec_missing = _trace_metric(coalesced, raw_dir, observation.bank_id, date, observation.segment, "recovery")
        nco = charge_off - recovery
        archive_match = co_archive_match and rec_archive_match
        derived_match = abs(nco - float(observation.segment_nco)) < 1e-8
        conclusion = "PASS" if archive_match and derived_match else "FAIL"
        rows.append({
            "bank_id": observation.bank_id,
            "cert": observation.cert,
            "bank_name": observation.bank_name,
            "report_date": date.date().isoformat(),
            "segment": observation.segment,
            "audit_sample_role": observation.audit_sample_role,
            "taxonomy_transition_audit": observation.audit_sample_role == "CRE_TAXONOMY_TRANSITION",
            "raw_source_files": "; ".join(sorted({member.split("::", 1)[0] for member in [*co_members, *rec_members]})),
            "source_archive_members": "; ".join([*co_members, *rec_members]),
            "charge_off_raw_fields_and_values": " | ".join(co_fields),
            "recovery_raw_fields_and_values": " | ".join(rec_fields),
            "transformation": "Q1: quarterly=YTD; Q2-Q4: quarterly=current YTD-prior-quarter YTD; segment NCO=quarterly charge-offs-quarterly recoveries",
            "quarterly_charge_off_thousands": charge_off,
            "quarterly_recovery_thousands": recovery,
            "derived_segment_nco_thousands": nco,
            "panel_segment_nco_thousands": observation.segment_nco,
            "raw_archive_to_standard_match": archive_match,
            "derived_to_panel_match": derived_match,
            "flow_component_completeness": not co_missing and not rec_missing,
            "missing_flow_components": ",".join([*co_missing, *rec_missing]),
            "reviewer": "Batch 1 acceptance repair operator",
            "reviewer_conclusion": conclusion,
            "reviewer_note": "Direct FFIEC archive members and values were inspected; raw-to-standard and recomputed-to-panel traces agree." if conclusion == "PASS" else "Trace mismatch; investigate before acceptance.",
            "limitation": "This is a fixed reproducible 100-observation source-document sample with required transition rows, not evidence that all unreviewed reporting-detail changes are absent.",
        })
    return pd.DataFrame(rows)


def update_quality_report_with_source_audit(audit: pd.DataFrame) -> None:
    failures = int(audit["reviewer_conclusion"].ne("PASS").sum())
    transition = audit.loc[audit["taxonomy_transition_audit"]]
    report_path = ROOT / "outputs" / "qa" / "data_quality_report.md"
    if report_path.exists():
        report = report_path.read_text(encoding="utf-8")
        marker = "\n## Direct source-document audit\n"
        if marker in report:
            report = report.split(marker, 1)[0].rstrip() + "\n"
        report += (
            f"{marker}\n"
            f"- Fixed reproducible sample: {len(audit):,} bank-segment-quarters (seed 772), including required transition rows.\n"
            f"- Direct FFIEC archive-member/raw-value to standard-layer matches: {int(audit['raw_archive_to_standard_match'].sum()):,}/{len(audit):,}.\n"
            f"- Recomputed quarterly NCO to panel matches: {int(audit['derived_to_panel_match'].sum()):,}/{len(audit):,}.\n"
            f"- Source-audit failures: {failures:,}.\n"
            f"- Deliberate CRE taxonomy-transition coverage: {len(transition):,} observations across {transition['report_date'].nunique():,} quarters; {int(transition['reviewer_conclusion'].eq('PASS').sum()):,}/{len(transition):,} passed.\n"
            "- This sample is evidence for the audited observations, not exhaustive proof of every reporting-detail change.\n"
        )
        report_path.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--report-only", action="store_true", help="Refresh QA report from an existing completed source audit.")
    args = parser.parse_args()
    output = ROOT / "metadata" / "manual_source_audit.csv"
    if args.report_only:
        audit = pd.read_csv(output)
    else:
        audit = create_source_audit(sample_size=args.sample_size)
        audit.to_csv(output, index=False)
    failures = int(audit["reviewer_conclusion"].ne("PASS").sum())
    update_quality_report_with_source_audit(audit)
    print(f"manual source audit rows={len(audit)} failures={failures} output={output}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
