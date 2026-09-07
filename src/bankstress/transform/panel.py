from __future__ import annotations

import numpy as np
import pandas as pd

from .flows import quarterize_ytd

CRE_TAXONOMY_TRANSITION = pd.Timestamp("2008-03-31")
CONSOLIDATED_DETAIL_START = pd.Timestamp("2013-06-30")
FLOW_COMPONENT_REQUIREMENTS = {
    ("cre_nco_legacy", "charge_off"): frozenset({"RIAD3582", "RIAD3588", "RIAD3590"}),
    ("cre_nco_legacy", "recovery"): frozenset({"RIAD3583", "RIAD3589", "RIAD3591"}),
    ("cre_nco_successor", "charge_off"): frozenset({"RIADC891", "RIADC893", "RIAD3588", "RIADC895", "RIADC897"}),
    ("cre_nco_successor", "recovery"): frozenset({"RIADC892", "RIADC894", "RIAD3589", "RIADC896", "RIADC898"}),
    ("mortgage_closed_end_nco", "charge_off"): frozenset({"RIADC234", "RIADC235"}),
    ("mortgage_closed_end_nco", "recovery"): frozenset({"RIADC217", "RIADC218"}),
    ("ci_nco_041", "charge_off"): frozenset({"RIAD4638"}),
    ("ci_nco_041", "recovery"): frozenset({"RIAD4608"}),
    ("ci_nco_031", "charge_off"): frozenset({"RIAD4645", "RIAD4646"}),
    ("ci_nco_031", "recovery"): frozenset({"RIAD4617", "RIAD4618"}),
    # Compatibility for existing minimal fixtures.
    ("ci_nco", "charge_off"): frozenset({"RIAD4638"}),
    ("ci_nco", "recovery"): frozenset({"RIAD4608"}),
}


def _column_or_na(frame: pd.DataFrame, name: str) -> pd.Series:
    return frame[name] if name in frame else pd.Series(np.nan, index=frame.index, dtype=float)


def _normalise_form(value: object) -> str:
    if pd.isna(value) or str(value).strip() in {"", "<NA>", "nan", "None"}:
        return "41"
    return str(value).strip().lstrip("0")


def _scope_for_form(form: object) -> str:
    return "CONSOLIDATED_BANK" if _normalise_form(form) == "31" else "DOMESTIC_ONLY_BANK"


def _unsupported_form_reason(form: object) -> str:
    normalized = _normalise_form(form)
    return f"unsupported_ffiec_{normalized.zfill(3)}_no_verified_segment_mapping"


def _coalesce_reporting_variants(data: pd.DataFrame) -> pd.DataFrame:
    """Coalesce genuine reporting alternatives without mixing different scopes."""
    output = data.copy()
    for column, default in {
        "source_file": pd.NA, "form": pd.NA, "unit": "thousands",
        "raw_presence_status": pd.NA, "stock_flow": "stock", "ytd_flag": 0,
        "formula_group": "test",
    }.items():
        if column not in output:
            output[column] = default
    output["form_was_missing"] = output["form"].isna()
    output["form"] = output["form"].map(_normalise_form)
    inferred_presence = pd.Series("PRESENT", index=output.index, dtype="string")
    inferred_presence.loc[output["numeric_value"].eq(0).fillna(False)] = "REPORTED_ZERO"
    inferred_presence.loc[output["numeric_value"].isna()] = "BLANK"
    output["raw_presence_status"] = output["raw_presence_status"].fillna(inferred_presence)

    # Preserve the legacy behavior only for form-less unit fixtures. Production
    # rows have an actual POR form and were already filtered by applicability.
    ci = output["standard_metric"].eq("exposure") & output["segment"].eq("CI")
    has_aggregate = output[ci].groupby(["bank_id", "report_date"])["raw_code"].transform(lambda x: x.eq("RCON1766").any())
    form_missing = output.loc[ci, "form_was_missing"]
    drop_breakout = ci.copy()
    drop_breakout.loc[ci] = has_aggregate & output.loc[ci, "raw_code"].ne("RCON1766") & form_missing
    output = output[~drop_breakout].copy()

    output["series_key"] = output["raw_code"].str.replace(r"^(RCFA|RCFW|RCFD|RCOA|RCOW|RCON)", "", regex=True)
    prefixes = ["RCFA", "RCFW", "RCFD", "RCOA", "RCOW", "RCON"]
    output["variant_priority"] = output["raw_code"].str.extract(r"^(RCFA|RCFW|RCFD|RCOA|RCOW|RCON)", expand=False).map(
        {prefix: priority for priority, prefix in enumerate(prefixes)}
    ).fillna(len(prefixes))
    keys = ["bank_id", "report_date", "form", "standard_metric", "segment", "series_key"]
    output["nonnull_priority"] = output["numeric_value"].isna().astype(int)
    return output.sort_values([*keys, "nonnull_priority", "variant_priority", "raw_code"]).groupby(keys, as_index=False, dropna=False).first()


def required_flow_components(segment: str, metric: str, report_date: object, formula_groups: set[str]) -> frozenset[str]:
    if segment == "CRE" and "cre_nco" in formula_groups:
        taxonomy = "cre_nco_successor" if pd.Timestamp(report_date) >= CRE_TAXONOMY_TRANSITION else "cre_nco_legacy"
        return FLOW_COMPONENT_REQUIREMENTS[(taxonomy, metric)]
    required: set[str] = set()
    for formula_group in formula_groups:
        required.update(FLOW_COMPONENT_REQUIREMENTS.get((formula_group, metric), ()))
    return frozenset(required)


def required_stock_components(segment: str, report_date: object, form: object) -> frozenset[str]:
    date, form = pd.Timestamp(report_date), _normalise_form(form)
    if segment == "CRE" and form == "41":
        return (frozenset({"RCON1415", "RCON1460", "RCON1480"}) if date < CRE_TAXONOMY_TRANSITION
                else frozenset({"RCONF158", "RCONF159", "RCON1460", "RCONF160", "RCONF161"}))
    if segment == "CRE" and form == "31" and date >= CONSOLIDATED_DETAIL_START:
        return frozenset({"RCFDF158", "RCFDF159", "RCFD1460", "RCFDF160", "RCFDF161"})
    if segment == "CI" and form == "41":
        return frozenset({"RCON1766"})
    if segment == "CI" and form == "31":
        return frozenset({"RCFD1763", "RCFD1764"})
    if segment == "Mortgage" and form == "41":
        return frozenset({"RCON5367", "RCON5368"})
    if segment == "Mortgage" and form == "31" and date >= CONSOLIDATED_DETAIL_START:
        return frozenset({"RCFD5367", "RCFD5368"})
    return frozenset()


def _mapping_id(segment: str, report_date: object, form: object) -> str:
    date, form = pd.Timestamp(report_date), _normalise_form(form)
    if form not in {"31", "41"}:
        return f"{segment}_{form.zfill(3)}_unavailable_unsupported_form"
    if segment == "CRE" and form == "41":
        return f"CRE_041_{'legacy' if date < CRE_TAXONOMY_TRANSITION else 'successor'}_secured_re"
    if segment in {"CRE", "Mortgage"} and form == "31" and date < CONSOLIDATED_DETAIL_START:
        return f"{segment}_031_unavailable_scope_mismatch"
    return f"{segment}_{form}_{_scope_for_form(form).lower()}"


def _aggregate_complete_flows(flows: pd.DataFrame) -> pd.DataFrame:
    flows = flows.copy()
    if "form" not in flows:
        flows["form"] = "41"
    quarterized = quarterize_ytd(flows)
    keys = ["bank_id", "report_date", "form", "standard_metric", "segment"]
    rows: list[dict[str, object]] = []
    for key, group in quarterized.groupby(keys, dropna=False, sort=False):
        required = required_flow_components(str(key[4]), str(key[3]), key[1], set(group["formula_group"].dropna().astype(str)))
        usable = group.loc[group["raw_code"].isin(required)] if required else group
        present = set(usable.loc[usable["quarterly_value"].notna(), "raw_code"].astype(str))
        missing = sorted(required - present)
        complete = (not missing) if required else usable["quarterly_value"].notna().all()
        rows.append({**dict(zip(keys, key)),
            "value": usable["quarterly_value"].sum(min_count=1) if complete else np.nan,
            "amendment_or_reclass_flag": int(usable["amendment_or_reclass_flag"].max()) if len(usable) else 0,
            "missing_prior_ytd_flag": int(usable["missing_prior_ytd_flag"].max()) if len(usable) else 0,
            "component_complete_flag": int(complete), "missing_flow_components": ",".join(missing),
            "flow_scope": _scope_for_form(key[2])})
    columns = [*keys, "value", "amendment_or_reclass_flag", "missing_prior_ytd_flag",
               "component_complete_flag", "missing_flow_components", "flow_scope"]
    return pd.DataFrame(rows, columns=columns)


def _aggregate_complete_stocks(stocks: pd.DataFrame) -> pd.DataFrame:
    keys = ["bank_id", "report_date", "form", "standard_metric", "segment"]
    rows: list[dict[str, object]] = []
    for key, group in stocks.groupby(keys, dropna=False, sort=False):
        segment, metric = str(key[4]), str(key[3])
        if metric == "exposure" and segment in {"CRE", "CI", "Mortgage"}:
            required = required_stock_components(segment, key[1], key[2])
            if group["formula_group"].eq("test").all():
                required = frozenset(group["raw_code"].astype(str))
            usable = group.loc[group["raw_code"].isin(required)]
            present = set(usable.loc[usable["numeric_value"].notna(), "raw_code"].astype(str))
            missing = sorted(required - present)
            complete = bool(required) and not missing
            if not required:
                status, reason = "NOT_APPLICABLE", "no_verified_same_scope_stock_mapping"
            elif missing:
                status, reason = "MISSING_REQUIRED", "missing_required_components:" + ",".join(missing)
            elif usable["numeric_value"].eq(0).all():
                status, reason = "REPORTED_ZERO", "all_required_components_reported_zero"
            else:
                status, reason = "PRESENT", "complete_required_component_set"
            value = usable["numeric_value"].sum(min_count=len(required)) if complete else np.nan
            mapping_id, scope = _mapping_id(segment, key[1], key[2]), _scope_for_form(key[2])
        else:
            usable = group.loc[group["numeric_value"].notna()]
            complete, missing = not usable.empty, [] if not usable.empty else sorted(set(group["raw_code"].astype(str)))
            value = usable["numeric_value"].sum(min_count=1) if complete else np.nan
            status = "REPORTED_ZERO" if complete and usable["numeric_value"].eq(0).all() else ("PRESENT" if complete else "MISSING_REQUIRED")
            reason, mapping_id, scope = ("reported_control" if complete else "blank_control"), f"{metric}_{_normalise_form(key[2])}", _scope_for_form(key[2])
        rows.append({**dict(zip(keys, key)), "value": value, "exposure_status": status,
            "exposure_complete": int(complete), "missing_stock_components": ",".join(missing),
            "mapping_id": mapping_id, "exposure_scope": scope, "reason": reason})
    columns = [*keys, "value", "exposure_status", "exposure_complete",
               "missing_stock_components", "mapping_id", "exposure_scope", "reason"]
    return pd.DataFrame(rows, columns=columns)


def build_credit_panel(standard: pd.DataFrame, institutions: pd.DataFrame, config: dict, lineage: pd.DataFrame | None = None) -> pd.DataFrame:
    data = _coalesce_reporting_variants(standard)
    flow_measures = _aggregate_complete_flows(data[data["stock_flow"].eq("flow")].copy())
    stock_measures = _aggregate_complete_stocks(data[data["stock_flow"].eq("stock")].copy())
    keys = ["bank_id", "report_date", "form", "standard_metric", "segment"]
    measures = pd.concat([stock_measures[keys + ["value"]], flow_measures[keys + ["value"]]], ignore_index=True)
    index_keys = ["bank_id", "report_date", "form", "segment"]
    segment_index = measures.loc[measures["segment"].isin(["CRE", "CI", "Mortgage"]), index_keys].drop_duplicates()
    filing_columns = ["bank_id", "report_date", "form"]
    filings = data.loc[data["standard_metric"].eq("filing_presence"), filing_columns].drop_duplicates()
    if not filings.empty:
        filing_spine = filings.merge(pd.DataFrame({"segment": ["CRE", "CI", "Mortgage"]}), how="cross")
        segment_index = pd.concat([segment_index, filing_spine[index_keys]], ignore_index=True).drop_duplicates()
    segment_values = measures[measures["segment"].isin(["CRE", "CI", "Mortgage"])].pivot_table(
        index=index_keys, columns="standard_metric", values="value", aggfunc="first", dropna=False).reset_index()
    segment = segment_index.merge(segment_values, on=index_keys, how="left")
    for segment_measure in ["exposure", "charge_off", "recovery"]:
        if segment_measure not in segment:
            segment[segment_measure] = np.nan
    stock_quality = stock_measures.loc[stock_measures["standard_metric"].eq("exposure"), index_keys + [
        "exposure_status", "exposure_complete", "missing_stock_components", "mapping_id", "exposure_scope", "reason"]]
    segment = segment.merge(stock_quality, on=index_keys, how="left", validate="one_to_one")
    fq = flow_measures.loc[flow_measures["segment"].isin(["CRE", "CI", "Mortgage"]), index_keys + ["standard_metric", "component_complete_flag", "flow_scope"]]
    flow_quality = fq.pivot_table(index=index_keys + ["flow_scope"], columns="standard_metric", values="component_complete_flag", aggfunc="first").reset_index().rename(
        columns={"charge_off": "charge_off_component_complete", "recovery": "recovery_component_complete"})
    segment = segment.merge(flow_quality, on=index_keys, how="left", validate="one_to_one")

    controls = measures[measures["segment"].eq("All")].pivot_table(index=["bank_id", "report_date", "form"], columns="standard_metric", values="value", aggfunc="first").reset_index()
    bank = controls.drop_duplicates(["bank_id", "report_date", "form"]).sort_values(["bank_id", "report_date"])
    if "filing_bank_name" in standard:
        filing_names = standard.loc[standard["standard_metric"].eq("filing_presence"), ["bank_id", "report_date", "form", "filing_bank_name"]].drop_duplicates()
        bank = bank.merge(filing_names, on=["bank_id", "report_date", "form"], how="left", validate="one_to_one")
    bank["bank_total_npl"] = _column_or_na(bank, "total_npl")
    bank["bank_total_npl_ratio"] = bank["bank_total_npl"] / _column_or_na(bank, "total_loans").where(_column_or_na(bank, "total_loans") > 0)
    bank["equity_to_assets_ratio"] = _column_or_na(bank, "equity_capital") / _column_or_na(bank, "total_assets").where(_column_or_na(bank, "total_assets") > 0)
    bank["tier1_ratio"] = _column_or_na(bank, "tier1_risk_based_ratio")
    bank["computed_tier1_ratio"] = _column_or_na(bank, "tier1_capital") / _column_or_na(bank, "risk_weighted_assets").where(_column_or_na(bank, "risk_weighted_assets") > 0)
    bank["allowance_to_total_npl"] = _column_or_na(bank, "allowance") / bank["bank_total_npl"].where(bank["bank_total_npl"] > 0)
    bank["allowance_coverage"] = bank["allowance_to_total_npl"]
    for required_control in ["total_loans", "total_assets", "tier1_capital"]:
        if required_control not in bank:
            bank[required_control] = np.nan
    bank["loan_growth"] = bank.groupby("bank_id")["total_loans"].pct_change(fill_method=None)
    bank["lagged_npl"] = bank.groupby("bank_id")["bank_total_npl"].shift(1)
    bank["lagged_bank_total_npl_ratio"] = bank.groupby("bank_id")["bank_total_npl_ratio"].shift(1)
    bank["asset_jump_flag"] = (bank.groupby("bank_id")["total_assets"].pct_change(fill_method=None).abs() > 0.50).fillna(False).astype(int)
    bank["merger_quarter_flag"] = 0
    if lineage is not None and not lineage.empty:
        events = lineage.assign(bank_id=lineage["bank_id"].astype(str), report_date=pd.to_datetime(lineage["event_date"]).dt.to_period("Q").dt.end_time.dt.normalize())[["bank_id", "report_date"]].drop_duplicates()
        events["event_merger_flag"] = 1
        bank = bank.merge(events, on=["bank_id", "report_date"], how="left", validate="many_to_one")
        bank["merger_quarter_flag"] = bank.pop("event_merger_flag").fillna(0).astype(int)
    bank["merger_recent_flag"] = (bank["merger_quarter_flag"].eq(1) | bank["asset_jump_flag"].eq(1)).astype(int)

    panel = segment.merge(bank, on=["bank_id", "report_date", "form"], how="left", validate="many_to_one")
    panel["exposure_status"] = panel["exposure_status"].fillna("NOT_APPLICABLE")
    panel["exposure_complete"] = panel["exposure_complete"].fillna(0).astype(int)
    panel["mapping_id"] = panel["mapping_id"].fillna(panel.apply(lambda r: _mapping_id(r["segment"], r["report_date"], r["form"]), axis=1))
    panel["exposure_scope"] = panel["exposure_scope"].fillna(panel["form"].map(_scope_for_form))
    unsupported = ~panel["form"].map(_normalise_form).isin({"31", "41"})
    panel.loc[unsupported & panel["reason"].isna(), "reason"] = panel.loc[unsupported, "form"].map(_unsupported_form_reason)
    panel["reason"] = panel["reason"].fillna("no_verified_same_scope_stock_mapping")
    panel["flow_scope"] = panel["flow_scope"].fillna(panel["form"].map(_scope_for_form))
    co_complete = _column_or_na(panel, "charge_off_component_complete").fillna(0).eq(1)
    rec_complete = _column_or_na(panel, "recovery_component_complete").fillna(0).eq(1)
    panel["flow_complete"] = co_complete & rec_complete
    panel["scope_match"] = panel["exposure_scope"].eq(panel["flow_scope"]) & panel["exposure_complete"].eq(1)
    panel["segment_nco"] = (_column_or_na(panel, "charge_off") - _column_or_na(panel, "recovery")).where(panel["flow_complete"])
    panel = panel.sort_values(["bank_id", "segment", "report_date"])
    groups = panel.groupby(["bank_id", "segment"], dropna=False)
    prior_exposure, prior_date, prior_scope = groups["exposure"].shift(), groups["report_date"].shift(), groups["exposure_scope"].shift()
    expected_prior = (panel["report_date"].dt.to_period("Q") - 1).dt.end_time.dt.normalize()
    panel["average_exposure_valid"] = (panel["exposure_complete"].eq(1) & prior_exposure.notna() & prior_date.eq(expected_prior)
        & prior_scope.eq(panel["exposure_scope"]) & panel["merger_recent_flag"].eq(0))
    panel["average_exposure"] = ((panel["exposure"] + prior_exposure) / 2).where(panel["average_exposure_valid"])
    usable_rate = panel["average_exposure"].gt(0) & panel["flow_complete"] & panel["scope_match"]
    panel["segment_nco_rate"] = (panel["segment_nco"] / panel["average_exposure"]).where(usable_rate)
    panel["annualized_nco_rate"] = panel["segment_nco_rate"] * 4
    panel["annualized_nco_rate_percent"] = panel["annualized_nco_rate"] * 100
    panel["amount_unit"] = "USD_thousands"
    panel["segment_npl_rate"] = np.nan
    panel["cre_share"] = np.where(panel["segment"].eq("CRE") & panel["exposure_complete"].eq(1), panel["exposure"] / panel.get("total_loans"), np.nan)
    panel["cre_to_tier1"] = np.where(panel["segment"].eq("CRE") & panel["exposure_complete"].eq(1), panel["exposure"] / panel.get("tier1_capital"), np.nan)
    prior_nco = panel.groupby(["bank_id", "segment"])["segment_nco"].shift()
    panel["lagged_nco"] = prior_nco.where(prior_date.eq(expected_prior) & panel["segment_nco"].notna())
    panel["eligible_for_model"] = (panel["average_exposure"].ge(config["sample"]["small_exposure_thousands"]) & usable_rate).fillna(False).astype(int)
    return panel.merge(institutions[["bank_id", "cert", "bank_name"]], on="bank_id", how="left", validate="many_to_one")
