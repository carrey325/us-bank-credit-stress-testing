from __future__ import annotations

import numpy as np
import pandas as pd

from .flows import quarterize_ytd


def _column_or_na(frame: pd.DataFrame, name: str) -> pd.Series:
    """Return a named column or an index-aligned missing series."""
    if name in frame:
        return frame[name]
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _coalesce_reporting_variants(data: pd.DataFrame) -> pd.DataFrame:
    """Prefer a single consolidated/domestic variant instead of double-counting it."""
    output = data.copy()
    # Unit-level callers may provide just the measurement columns; production
    # standard-layer rows always carry the archive provenance.
    if "source_file" not in output:
        output["source_file"] = pd.NA
    # The aggregate domestic C&I item (RCON1766) is available for many reporters
    # alongside its geographic breakout (RCFD1763/1764).  Use the aggregate when
    # present; otherwise retain the breakout sum for reporters without it.
    ci = output["standard_metric"].eq("exposure") & output["segment"].eq("CI")
    ci_keys = ["bank_id", "report_date"]
    has_ci_aggregate = output[ci].groupby(ci_keys)["raw_code"].transform(lambda values: values.eq("RCON1766").any())
    drop_ci_breakout = ci.copy()
    drop_ci_breakout.loc[ci] = has_ci_aggregate & output.loc[ci, "raw_code"].ne("RCON1766")
    output = output[~drop_ci_breakout].copy()
    output["series_key"] = output["raw_code"].str.replace(r"^(RCON|RCFD)", "", regex=True)
    keys = ["bank_id", "report_date", "standard_metric", "segment", "series_key"]
    output = output.sort_values([*keys, "raw_code"]).groupby(keys, as_index=False).agg(
        numeric_value=("numeric_value", "max"), raw_code=("raw_code", "first"), stock_flow=("stock_flow", "first"),
        ytd_flag=("ytd_flag", "first"), formula_group=("formula_group", "first"), source_file=("source_file", "first")
    )
    return output


def build_credit_panel(standard: pd.DataFrame, institutions: pd.DataFrame, config: dict, lineage: pd.DataFrame | None = None) -> pd.DataFrame:
    data = _coalesce_reporting_variants(standard)
    flows = data[data["stock_flow"].eq("flow")].copy()
    stocks = data[data["stock_flow"].eq("stock")].copy()
    flows = quarterize_ytd(flows)
    flows["value"] = flows["quarterly_value"]
    stocks["value"] = stocks["numeric_value"]
    combined = pd.concat([stocks, flows], ignore_index=True, sort=False)
    aggregate_keys = ["bank_id", "report_date", "standard_metric", "segment"]
    measures = combined.groupby(aggregate_keys, as_index=False, dropna=False).agg(
        value=("value", lambda values: values.sum(min_count=1)),
        amendment_or_reclass_flag=("amendment_or_reclass_flag", "max"),
        missing_prior_ytd_flag=("missing_prior_ytd_flag", "max"),
    )
    measures["amendment_or_reclass_flag"] = measures["amendment_or_reclass_flag"].fillna(0).astype(int)
    measures["missing_prior_ytd_flag"] = measures["missing_prior_ytd_flag"].fillna(0).astype(int)
    segment = measures[measures.segment.isin(["CRE", "CI", "Mortgage"])].pivot_table(
        index=["bank_id", "report_date", "segment"], columns="standard_metric", values="value", aggfunc="first"
    ).reset_index()
    controls = measures[measures.segment.eq("All")].pivot_table(
        index=["bank_id", "report_date"], columns="standard_metric", values="value", aggfunc="first"
    ).reset_index()
    # Compute bank-level controls once on a unique, chronologically ordered
    # bank-quarter frame.  Computing these after segment expansion would make
    # `shift`/`pct_change` step through CRE, C&I, and Mortgage rows at the same
    # report date and leak values across segment boundaries.
    bank = controls.drop_duplicates(["bank_id", "report_date"]).copy()
    bank = bank.sort_values(["bank_id", "report_date"])
    bank["bank_total_npl"] = _column_or_na(bank, "total_npl")
    bank["bank_total_npl_ratio"] = bank["bank_total_npl"] / _column_or_na(bank, "total_loans").where(_column_or_na(bank, "total_loans") > 0)
    bank["equity_to_assets_ratio"] = _column_or_na(bank, "equity_capital") / _column_or_na(bank, "total_assets").where(_column_or_na(bank, "total_assets") > 0)
    bank["tier1_ratio"] = _column_or_na(bank, "tier1_risk_based_ratio")
    bank["allowance_to_total_npl"] = _column_or_na(bank, "allowance") / bank["bank_total_npl"].where(bank["bank_total_npl"] > 0)
    # Compatibility name retained for the existing Batch 2 interface.  It is
    # now the proposal's allowance/noncurrent-loans definition, not allowance/
    # total-loans.
    bank["allowance_coverage"] = bank["allowance_to_total_npl"]
    bank["loan_growth"] = bank.groupby("bank_id")["total_loans"].pct_change(fill_method=None)
    bank["lagged_npl"] = bank.groupby("bank_id")["bank_total_npl"].shift(1)
    bank["lagged_bank_total_npl_ratio"] = bank.groupby("bank_id")["bank_total_npl_ratio"].shift(1)
    assets_change = bank.groupby("bank_id")["total_assets"].pct_change(fill_method=None).abs()
    bank["asset_jump_flag"] = (assets_change > 0.50).astype(int)
    bank["merger_quarter_flag"] = 0
    if lineage is not None and not lineage.empty:
        events = lineage.assign(bank_id=lineage["bank_id"].astype(str), report_date=pd.to_datetime(lineage["event_date"]).dt.to_period("Q").dt.end_time.dt.normalize())[["bank_id", "report_date"]].drop_duplicates()
        events["event_merger_flag"] = 1
        bank = bank.merge(events, on=["bank_id", "report_date"], how="left", validate="one_to_one")
        bank["merger_quarter_flag"] = bank["event_merger_flag"].fillna(0).astype(int)
        bank = bank.drop(columns="event_merger_flag")
    bank["merger_recent_flag"] = (bank["merger_quarter_flag"].eq(1) | bank["asset_jump_flag"].eq(1)).astype(int)

    panel = segment.merge(bank, on=["bank_id", "report_date"], how="left", validate="many_to_one")
    panel["segment_nco"] = panel.get("charge_off") - panel.get("recovery")
    panel = panel.sort_values(["bank_id", "segment", "report_date"])
    panel["average_exposure"] = panel.groupby(["bank_id", "segment"])["exposure"].transform(lambda x: (x + x.shift()) / 2)
    panel["segment_nco_rate"] = panel["segment_nco"] / panel["average_exposure"].where(panel["average_exposure"] > 0)
    panel["annualized_nco_rate"] = panel["segment_nco_rate"] * 4
    # The Call Report mapping does not provide a consistent segment NPL series.
    # Do not divide the bank-level total NPL stock by a segment denominator.
    # `bank_total_npl[_ratio]` and its lag are the documented bank-level fallback.
    panel["segment_npl_rate"] = np.nan
    panel["cre_share"] = np.where(panel["segment"].eq("CRE"), panel["exposure"] / panel.get("total_loans"), np.nan)
    panel["cre_to_tier1"] = np.where(panel["segment"].eq("CRE"), panel["exposure"] / panel.get("tier1_capital"), np.nan)
    panel["lagged_nco"] = panel.groupby(["bank_id", "segment"])["segment_nco"].shift()
    panel["eligible_for_model"] = (panel["average_exposure"] >= config["sample"]["small_exposure_thousands"]).fillna(False).astype(int)
    panel = panel.merge(institutions[["bank_id", "cert", "bank_name"]], on="bank_id", how="left", validate="many_to_one")
    return panel
