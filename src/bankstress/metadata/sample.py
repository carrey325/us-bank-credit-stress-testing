from __future__ import annotations

from pathlib import Path
import requests
import pandas as pd


FDIC_FINANCIALS = "https://banks.data.fdic.gov/api/financials"
FDIC_INSTITUTIONS = "https://banks.data.fdic.gov/api/institutions"
FDIC_HISTORY = "https://banks.data.fdic.gov/api/history"


def _api(url: str, params: dict) -> list[dict]:
    response = requests.get(url, params={**params, "format": "json"}, timeout=60)
    response.raise_for_status()
    return [item["data"] for item in response.json()["data"]]


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
    frame["credit_card_ratio"] = frame["LNCRCD"].fillna(0) / frame["LNLSNET"].replace(0, pd.NA)
    frame["specialized_business_flag"] = (frame["credit_card_ratio"].fillna(0) > 0.50).astype(int)
    selected = frame[frame["specialized_business_flag"].eq(0)].sort_values("ASSET", ascending=False).head(policy["target_core_banks"]).copy()
    frame["bank_id"] = frame["RSSDID"].astype("Int64").astype(str)
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
    frame.loc[frame["specialized_business_flag"].eq(1), "exclusion_reason"] = "credit_card_dominant"
    frame.loc[frame["specialized_business_flag"].eq(0) & frame["core_sample_flag"].eq(0), "exclusion_reason"] = "outside_ranked_core_target"
    columns = ["bank_id", "cert", "rssd_id", "bank_name", "parent_name", "assets", "form_type", "first_report_date", "last_report_date", "active_2025q4", "failed_flag", "acquired_flag", "specialized_business_flag", "core_sample_flag", "exclusion_reason"]
    out = frame[columns].sort_values("bank_id")
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
    out.loc[out["core_sample_flag"].eq(0), ["bank_id", "exclusion_reason"]].rename(columns={"exclusion_reason": "reason"}).assign(source="FDIC 2025Q4 screen", reviewed_at=pd.Timestamp.utcnow().date()).to_csv(metadata_dir / "exclusion_log.csv", index=False)
    return out[out["core_sample_flag"].eq(1)].copy()


def update_sample_coverage(metadata_dir: Path, standard: pd.DataFrame, min_history_quarters: int) -> pd.DataFrame:
    """Record actual reporting coverage and exclude any selected bank below policy."""
    institutions = pd.read_csv(metadata_dir / "institutions.csv", dtype={"bank_id": str, "cert": str, "rssd_id": str})
    coverage = standard.assign(bank_id=standard["bank_id"].astype(str)).groupby("bank_id").report_date.agg(["min", "max", "nunique"]).reset_index()
    institutions = institutions.merge(coverage, on="bank_id", how="left")
    selected = institutions["core_sample_flag"].eq(1)
    insufficient = selected & institutions["nunique"].fillna(0).lt(min_history_quarters)
    institutions.loc[insufficient, "core_sample_flag"] = 0
    institutions.loc[insufficient, "exclusion_reason"] = "insufficient_report_history"
    institutions["first_report_date"] = institutions["min"].dt.strftime("%Y-%m-%d")
    institutions["last_report_date"] = institutions["max"].dt.strftime("%Y-%m-%d")
    institutions = institutions.drop(columns=["min", "max", "nunique"])
    institutions.to_csv(metadata_dir / "institutions.csv", index=False)
    exclusions = institutions[institutions["core_sample_flag"].eq(0)][["bank_id", "exclusion_reason"]].rename(columns={"exclusion_reason": "reason"}).assign(source="FDIC/Call Report sample screen", reviewed_at=pd.Timestamp.utcnow().date())
    exclusions.to_csv(metadata_dir / "exclusion_log.csv", index=False)
    return institutions[institutions["core_sample_flag"].eq(1)].copy()
