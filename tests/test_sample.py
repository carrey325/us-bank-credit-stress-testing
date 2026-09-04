from __future__ import annotations

import pandas as pd
import pytest

from bankstress.metadata import sample


def _review(bank_id: str, *, credit: str = "no", auto: str = "no", custody: str = "no", broker: str = "no") -> dict[str, str]:
    return {
        "bank_id": bank_id,
        "review_period": "2025-12-31",
        "primary_source": "Official legal-entity filing",
        "primary_source_url": "https://example.test/primary-source",
        "evidence_summary": "Primary-source review completed for the legal entity.",
        "credit_card_assessment": credit,
        "auto_finance_assessment": auto,
        "custody_asset_servicing_assessment": custody,
        "broker_dealer_trading_assessment": broker,
    }


def _financial(bank_id: str, cert: str, name: str, assets: int, credit_cards: int = 0) -> dict[str, object]:
    return {
        "RSSDID": bank_id,
        "CERT": cert,
        "NAME": name,
        "NAMEHCR": "Test parent",
        "ASSET": assets,
        "CALLFORM": 41,
        "REPDTE": "20251231",
        "LNCRCD": credit_cards,
        "LNLSNET": 100,
        "ACTIVE": 1,
        "BKCLASS": "NM",
    }


def test_primary_source_specialization_gate_excludes_all_reviewed_prohibited_types(tmp_path, monkeypatch):
    reviews = pd.DataFrame([
        _review("1"),
        _review("2", credit="yes"),
        _review("3", auto="yes"),
        _review("4", custody="yes"),
        _review("5", broker="yes"),
    ])
    reviews.to_csv(tmp_path / sample.REVIEW_FILE, index=False)
    financials = [
        _financial("2", "2", "Credit card bank", 500, credit_cards=90),
        _financial("3", "3", "Auto finance bank", 400),
        _financial("4", "4", "Custody bank", 300),
        _financial("5", "5", "Broker dealer bank", 200),
        _financial("1", "1", "Traditional bank", 100),
    ]
    monkeypatch.setattr(sample, "_api", lambda url, params: financials if url == sample.FDIC_FINANCIALS else [])

    selected = sample.build_institutions(tmp_path, {"sample": {"asset_min_thousands": 1, "asset_max_thousands": 999, "target_core_banks": 1, "specialized_credit_card_ratio": 0.50}})

    assert selected["bank_id"].tolist() == ["1"]
    institutions = pd.read_csv(tmp_path / "institutions.csv", dtype={"bank_id": str})
    excluded = institutions.set_index("bank_id")
    assert excluded.loc["2", "exclusion_reason"] == "credit_card_dominant"
    assert excluded.loc["3", "exclusion_reason"] == "auto_finance_dominant"
    assert excluded.loc["4", "exclusion_reason"] == "custody_asset_servicing_dominant"
    assert excluded.loc["5", "exclusion_reason"] == "broker_dealer_trading_dominant"
    assert excluded.loc[["2", "3", "4", "5"], "core_sample_flag"].eq(0).all()


def test_sample_selection_fails_closed_without_enough_primary_source_reviews(tmp_path, monkeypatch):
    pd.DataFrame([_review("1")]).to_csv(tmp_path / sample.REVIEW_FILE, index=False)
    financials = [
        _financial("1", "1", "Traditional bank", 200),
        _financial("2", "2", "Unreviewed bank", 100),
    ]
    monkeypatch.setattr(sample, "_api", lambda url, params: financials if url == sample.FDIC_FINANCIALS else [])

    with pytest.raises(RuntimeError, match="primary-source-reviewed"):
        sample.build_institutions(tmp_path, {"sample": {"asset_min_thousands": 1, "asset_max_thousands": 999, "target_core_banks": 2}})
