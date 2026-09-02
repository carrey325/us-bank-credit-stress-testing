from __future__ import annotations

import numpy as np
import pandas as pd

from .flows import quarterize_ytd


def _coalesce_reporting_variants(data: pd.DataFrame) -> pd.DataFrame:
    """Prefer a single consolidated/domestic variant instead of double-counting it."""
    output = data.copy()
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
        ytd_flag=("ytd_flag", "first"), formula_group=("formula_group", "first")
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
    panel = segment.merge(controls, on=["bank_id", "report_date"], how="left")
    panel["segment_nco"] = panel.get("charge_off") - panel.get("recovery")
    panel = panel.sort_values(["bank_id", "segment", "report_date"])
    panel["average_exposure"] = panel.groupby(["bank_id", "segment"])["exposure"].transform(lambda x: (x + x.shift()) / 2)
    panel["segment_nco_rate"] = panel["segment_nco"] / panel["average_exposure"].where(panel["average_exposure"] > 0)
    panel["annualized_nco_rate"] = panel["segment_nco_rate"] * 4
    panel["segment_npl_rate"] = panel.get("total_npl") / panel["exposure"].where(panel["exposure"] > 0)
    panel["cre_share"] = np.where(panel["segment"].eq("CRE"), panel["exposure"] / panel.get("total_loans"), np.nan)
    panel["cre_to_tier1"] = np.where(panel["segment"].eq("CRE"), panel["exposure"] / panel.get("tier1_capital"), np.nan)
    panel["allowance_coverage"] = panel.get("allowance") / panel.get("total_loans").where(panel.get("total_loans") > 0)
    panel["tier1_ratio"] = panel.get("tier1_capital") / panel.get("total_assets").where(panel.get("total_assets") > 0)
    panel["loan_growth"] = panel.groupby("bank_id")["total_loans"].pct_change(fill_method=None)
    panel["lagged_nco"] = panel.groupby(["bank_id", "segment"])["segment_nco"].shift()
    panel["lagged_npl"] = panel.groupby("bank_id")["total_npl"].shift()
    panel["eligible_for_model"] = (panel["average_exposure"] >= config["sample"]["small_exposure_thousands"]).fillna(False).astype(int)
    assets_change = panel.groupby("bank_id")["total_assets"].pct_change(fill_method=None).abs()
    panel["asset_jump_flag"] = (assets_change > 0.50).astype(int)
    panel["merger_quarter_flag"] = 0
    if lineage is not None and not lineage.empty:
        events = lineage.assign(bank_id=lineage["bank_id"].astype(str), report_date=pd.to_datetime(lineage["event_date"]).dt.to_period("Q").dt.end_time.dt.normalize())[["bank_id", "report_date"]].drop_duplicates()
        events["event_merger_flag"] = 1
        panel = panel.merge(events, on=["bank_id", "report_date"], how="left")
        panel["merger_quarter_flag"] = panel["event_merger_flag"].fillna(0).astype(int)
        panel = panel.drop(columns="event_merger_flag")
    panel["merger_recent_flag"] = (panel["merger_quarter_flag"].eq(1) | panel["asset_jump_flag"].eq(1)).astype(int)
    panel = panel.merge(institutions[["bank_id", "cert", "bank_name"]], on="bank_id", how="left", validate="many_to_one")
    return panel
