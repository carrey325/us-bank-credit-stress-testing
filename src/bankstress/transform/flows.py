from __future__ import annotations

import pandas as pd


def quarterize_ytd(frame: pd.DataFrame, value_column: str = "numeric_value") -> pd.DataFrame:
    """Convert YTD Call Report flows to quarterly values without imputing gaps.

    A missing prior quarter produces missing quarterly flow and an auditable reason.
    Downward YTD revisions are retained and flagged; recoveries and NCO may be negative.
    """
    keys = ["bank_id", "standard_metric", "segment", "raw_code"]
    out = frame.sort_values([*keys, "report_date"]).copy()
    date = pd.to_datetime(out["report_date"])
    out["year"] = date.dt.year
    out["quarter"] = date.dt.quarter
    grouped = out.groupby([*keys, "year"], dropna=False)
    prior = grouped[value_column].shift()
    prior_quarter = grouped["quarter"].shift()
    out["quarterly_value"] = out[value_column]
    after_q1 = out["quarter"].ne(1)
    valid_prior = prior.notna() & prior_quarter.eq(out["quarter"] - 1)
    out.loc[after_q1 & valid_prior, "quarterly_value"] = out.loc[after_q1 & valid_prior, value_column] - prior[after_q1 & valid_prior]
    out.loc[after_q1 & ~valid_prior, "quarterly_value"] = pd.NA
    out["missing_prior_ytd_flag"] = (after_q1 & ~valid_prior).astype(int)
    out["amendment_or_reclass_flag"] = (after_q1 & valid_prior & (out["quarterly_value"] < 0)).astype(int)
    out["quarterization_reason"] = pd.NA
    out.loc[out["missing_prior_ytd_flag"].eq(1), "quarterization_reason"] = "missing_or_nonconsecutive_prior_ytd"
    out.loc[out["amendment_or_reclass_flag"].eq(1), "quarterization_reason"] = "ytd_decrease_retained"
    return out.drop(columns=["year", "quarter"])
