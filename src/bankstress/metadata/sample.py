from __future__ import annotations

from pathlib import Path
import requests
import pandas as pd


FDIC_FINANCIALS = "https://banks.data.fdic.gov/api/financials"
FDIC_INSTITUTIONS = "https://banks.data.fdic.gov/api/institutions"
FDIC_HISTORY = "https://banks.data.fdic.gov/api/history"
REVIEW_FILE = "specialized_business_review.csv"
REVIEW_CATEGORY_COLUMNS = (
    "credit_card_assessment",
    "auto_finance_assessment",
    "custody_asset_servicing_assessment",
    "broker_dealer_trading_assessment",
)
REVIEW_REQUIRED_COLUMNS = (
    "bank_id",
    "review_period",
    "primary_source",
    "primary_source_url",
    "evidence_summary",
    *REVIEW_CATEGORY_COLUMNS,
)


def _api(url: str, params: dict) -> list[dict]:
    response = requests.get(url, params={**params, "format": "json"}, timeout=60)
    response.raise_for_status()
    return [item["data"] for item in response.json()["data"]]


def _load_specialized_review(metadata_dir: Path) -> pd.DataFrame:
    """Load the legal-entity, primary-source review that gates the core sample.

    The source review is deliberately a tracked research input rather than a
    name-based heuristic.  A parent with a broker-dealer or an insurance
    affiliate is not enough to classify an FDIC legal entity as specialized.
    Conversely, reviewed ``yes`` findings always win over a low Call Report
    credit-card ratio.
    """
    path = metadata_dir / REVIEW_FILE
    if not path.exists():
        raise FileNotFoundError(f"Batch 1 requires {path} before selecting a core sample")
    review = pd.read_csv(path, dtype=str).fillna("")
    missing = [column for column in REVIEW_REQUIRED_COLUMNS if column not in review]
    if missing:
        raise ValueError(f"{path} is missing required review columns: {', '.join(missing)}")
    review["bank_id"] = review["bank_id"].astype(str)
    if review["bank_id"].duplicated().any():
        duplicates = ", ".join(review.loc[review["bank_id"].duplicated(), "bank_id"].tolist())
        raise ValueError(f"{path} has duplicate bank reviews: {duplicates}")
    for column in REVIEW_CATEGORY_COLUMNS:
        values = set(review[column].str.lower())
        if not values.issubset({"yes", "no"}):
            raise ValueError(f"{path} column {column} must contain only yes/no")
    required_text = ["review_period", "primary_source", "primary_source_url", "evidence_summary"]
    if review[required_text].eq("").any(axis=None):
        raise ValueError(f"{path} has an incomplete primary-source review row")
    return review


def _write_exclusion_log(metadata_dir: Path, institutions: pd.DataFrame, source: str) -> None:
    columns = [
        "bank_id", "cert", "bank_name", "reason", "specialized_business_flag",
        "specialized_review_status", "specialized_review_period", "primary_source",
        "primary_source_url", "evidence_summary",
    ]
    excluded = institutions.loc[institutions["core_sample_flag"].eq(0)].copy()
    excluded["reason"] = excluded["exclusion_reason"]
    for column in columns:
        if column not in excluded:
            excluded[column] = pd.NA
    excluded[columns].assign(source=source, reviewed_at=pd.Timestamp.utcnow().date()).to_csv(
        metadata_dir / "exclusion_log.csv", index=False
    )


def build_institutions(metadata_dir: Path, config: dict) -> pd.DataFrame:
    """Create a transparent candidate/core universe from the FDIC public API."""
    policy = config["sample"]
    fields = "CERT,RSSDID,NAME,NAMEHCR,ASSET,CALLFORM,REPDTE,LNCRCD,LNLSNET,ACTIVE,BKCLASS"
    filters = (f"REPDTE:20251231 AND ASSET:[{policy['asset_min_thousands']} TO "
               f"{policy['asset_max_thousands']}] AND ACTIVE:1")
    data = _api(FDIC_FINANCIALS, {"filters": filters, "fields": fields, "limit": 10000, "sort_by": "ASSET", "sort_order": "DESC"})
    frame = pd.DataFrame(data)
    if frame.empty:
        raise RuntimeError("FDIC returned no 2025Q4 asset-range candidates")
    review = _load_specialized_review(metadata_dir)
    frame["bank_id"] = frame["RSSDID"].astype("Int64").astype(str)
    frame = frame.merge(review, on="bank_id", how="left")
    frame["specialized_review_status"] = frame["review_period"].notna().map({True: "reviewed", False: "review_required"})
    for column in REVIEW_CATEGORY_COLUMNS:
        frame[column] = frame[column].fillna("").str.lower()
    card_loans = pd.to_numeric(frame["LNCRCD"], errors="coerce").astype(float)
    net_loans = pd.to_numeric(frame["LNLSNET"], errors="coerce").astype(float).where(lambda values: values.ne(0))
    frame["credit_card_ratio"] = card_loans / net_loans
    credit_card_dominant = frame["credit_card_ratio"].gt(policy.get("specialized_credit_card_ratio", 0.50)) | frame["credit_card_assessment"].eq("yes")
    auto_finance_dominant = frame["auto_finance_assessment"].eq("yes")
    custody_dominant = frame["custody_asset_servicing_assessment"].eq("yes")
    broker_dealer_dominant = frame["broker_dealer_trading_assessment"].eq("yes")
    reasons = pd.Series(pd.NA, index=frame.index, dtype="object")
    reasons.loc[credit_card_dominant] = "credit_card_dominant"
    reasons.loc[auto_finance_dominant] = "auto_finance_dominant"
    reasons.loc[custody_dominant] = "custody_asset_servicing_dominant"
    reasons.loc[broker_dealer_dominant] = "broker_dealer_trading_dominant"
    frame["specialized_business_flag"] = reasons.notna().astype(int)
    frame["specialized_classification_reason"] = reasons
    eligible = frame[frame["specialized_review_status"].eq("reviewed") & frame["specialized_business_flag"].eq(0)]
    selected = eligible.sort_values("ASSET", ascending=False).head(policy["target_core_banks"]).copy()
    if len(selected) < policy["target_core_banks"]:
        raise RuntimeError(
            "Insufficient primary-source-reviewed, non-specialized institutions for the core target; "
            f"review more traditional loan/deposit candidates before lowering the target ({len(selected)} available)."
        )
    frame["cert"] = frame["CERT"].astype("Int64").astype(str)
    frame["rssd_id"] = frame["bank_id"]
    frame["bank_name"] = frame["NAME"]
    frame["parent_name"] = frame.get("NAMEHCR")
    frame["assets"] = frame["ASSET"]
    frame["form_type"] = frame["CALLFORM"].astype("Int64").astype(str)
    frame["first_report_date"] = pd.NA
    frame["last_report_date"] = "2025-12-31"
    frame["active_2025q4"] = 1
    frame["failed_flag"] = 0
    frame["acquired_flag"] = 0
    selected_ids = set(selected["RSSDID"].astype("Int64").astype(str))
    frame["core_sample_flag"] = frame["bank_id"].isin(selected_ids).astype(int)
    frame["exclusion_reason"] = pd.NA
    frame.loc[frame["specialized_business_flag"].eq(1), "exclusion_reason"] = frame.loc[frame["specialized_business_flag"].eq(1), "specialized_classification_reason"]
    frame.loc[frame["specialized_review_status"].eq("review_required") & frame["specialized_business_flag"].eq(0), "exclusion_reason"] = "primary_source_review_required"
    frame.loc[frame["specialized_review_status"].eq("reviewed") & frame["specialized_business_flag"].eq(0) & frame["core_sample_flag"].eq(0), "exclusion_reason"] = "outside_ranked_core_target"
    columns = ["bank_id", "cert", "rssd_id", "bank_name", "parent_name", "assets", "form_type", "first_report_date", "last_report_date", "active_2025q4", "failed_flag", "acquired_flag", "specialized_business_flag", "core_sample_flag", "exclusion_reason", "specialized_review_status", "review_period", "primary_source", "primary_source_url", "evidence_summary", *REVIEW_CATEGORY_COLUMNS]
    out = frame[columns].sort_values("bank_id")
    out = out.rename(columns={"review_period": "specialized_review_period"})
    metadata_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(metadata_dir / "institutions.csv", index=False)
    lineage_rows: list[dict] = []
    # CHANGECODE 713 is branch-granular.  We collapse its distinct acquisition dates
    # to a conservative bank-quarter merger flag, without claiming a virtual bank.
    for record in out.loc[out["core_sample_flag"].eq(1), ["bank_id", "cert"]].itertuples(index=False):
        events = _api(FDIC_HISTORY, {"filters": f"CERT:{record.cert} AND CHANGECODE:713", "fields": "CERT,EFFDATE,ACQDATE,CHANGECODE_DESC", "limit": 10000})
        for event in events:
            event_date = event.get("ACQDATE") or event.get("EFFDATE")
            if not event_date or str(event_date).startswith("9999"):
                continue
            event_date = str(event_date)[:10]
            if "2005-01-01" <= event_date <= "2025-12-31":
                lineage_rows.append({"bank_id": record.bank_id, "event_date": event_date, "event_type": event.get("CHANGECODE_DESC", "Merger/consolidation"), "source": "FDIC BankFind history API (CHANGECODE 713)", "notes": "Branch-level events collapsed to one bank-quarter flag."})
    lineage = pd.DataFrame(lineage_rows, columns=["bank_id", "event_date", "event_type", "source", "notes"]).drop_duplicates(["bank_id", "event_date", "event_type"])
    lineage.to_csv(metadata_dir / "institution_lineage.csv", index=False)
    _write_exclusion_log(metadata_dir, out, "FDIC 2025Q4 screen plus primary-source specialization review")
    return out[out["core_sample_flag"].eq(1)].copy()


def update_sample_coverage(metadata_dir: Path, standard: pd.DataFrame, min_history_quarters: int) -> pd.DataFrame:
    """Record actual reporting coverage and exclude any selected bank below policy."""
    institutions = pd.read_csv(metadata_dir / "institutions.csv", dtype={"bank_id": str, "cert": str, "rssd_id": str})
    coverage = standard.assign(bank_id=standard["bank_id"].astype(str)).groupby("bank_id").report_date.agg(["min", "max", "nunique"]).reset_index()
    institutions = institutions.merge(coverage, on="bank_id", how="left")
    selected = institutions["core_sample_flag"].eq(1)
    invalid_specialization = selected & (
        institutions["specialized_business_flag"].eq(1)
        | institutions["specialized_review_status"].ne("reviewed")
    )
    institutions.loc[invalid_specialization, "core_sample_flag"] = 0
    institutions.loc[invalid_specialization, "exclusion_reason"] = "specialization_review_gate"
    selected = institutions["core_sample_flag"].eq(1)
    insufficient = selected & institutions["nunique"].fillna(0).lt(min_history_quarters)
    institutions.loc[insufficient, "core_sample_flag"] = 0
    institutions.loc[insufficient, "exclusion_reason"] = "insufficient_report_history"
    institutions["first_report_date"] = institutions["min"].dt.strftime("%Y-%m-%d")
    institutions["last_report_date"] = institutions["max"].dt.strftime("%Y-%m-%d")
    institutions = institutions.drop(columns=["min", "max", "nunique"])
    institutions.to_csv(metadata_dir / "institutions.csv", index=False)
    _write_exclusion_log(metadata_dir, institutions, "FDIC/Call Report sample screen plus primary-source specialization review")
    return institutions[institutions["core_sample_flag"].eq(1)].copy()
