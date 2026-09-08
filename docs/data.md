# Data definitions and source decisions

## Coverage and unit of observation

The retained panel covers 2005Q1–2025Q4: 84 quarters, 33 reporting banks, and
8,145 bank–segment–quarter rows. CRE, C&I, and closed-end residential mortgage
are the historical segments. The primary forecasting comparisons use CRE and
C&I; the final C&I stress comparison has 31 banks with usable jump-off states.
Sample size varies with reporting history, component availability, predictors,
and realized outcomes. Mortgage history is not a Mortgage stress model.

`metadata/institutions.csv` contains candidate institutions as well as the final
sample. Use `core_sample_flag`, not its total row count. Banks are reporting
legal entities identified by RSSD/FDIC identifiers; parent names are descriptive.
The selection emphasizes regional commercial banks, with configured asset and
history filters and source-based reviews of specialized business models. It is
not a probability sample of all U.S. banks or a survivorship-free industry panel.

## Collection and transformation

| Input | Source / lineage | Transformation |
| --- | --- | --- |
| Call Report archives | [FFIEC CDR](https://cdr.ffiec.gov/public/pws/downloadbulkdata.aspx); [download manifest](../data/manifests/ffiec_manifest.csv) | Extract schedules, bank identifiers, filing forms, and mapped raw fields |
| Field definitions | [73 distinct codes](../metadata/field_mapping.csv); [source evidence](../metadata/field_mapping_evidence.csv) | Match effective date, form, reporting scope, component membership, and units |
| Bank characteristics | [FDIC BankFind API](https://banks.data.fdic.gov/docs/); [institutions](../metadata/institutions.csv), [events](../metadata/institution_lineage.csv) | Select institutions, retain exclusions, flag merger/reclassification periods |
| Noncurrent loans | [FDIC collector](../src/bankstress/io/fdic_financials.py); [manifest](../metadata/fdic_noncurrent_manifest.csv) | Bank-level controls; not a substitute for segment NPL rates |
| Macro history | [FRED](https://fred.stlouisfed.org/) / [ALFRED](https://alfred.stlouisfed.org/); [manifest](../metadata/macro_download_manifest.csv) | Configured quarterly aggregation, transformations, and availability rules |
| Stress inputs | [Final 2026 Fed scenarios](https://www.federalreserve.gov/publications/2026-stress-test-scenarios.htm); [manifest](../metadata/fed_2026_scenario_manifest.csv) | Validate source bytes, transform levels/growth, and construct nine-quarter predictors |

The 73-code count measures the mapping inventory, including historical and form
variants. It does not mean every field is present for every observation. The
current sample is more precisely described as **30+ banks and 7K+ observations**
than as an exact 30-bank panel.

## Financial definitions

- **Quarterly NCO:** quarterly gross charge-offs minus quarterly recoveries.
  Q1 uses reported YTD flow; later quarters subtract the immediately preceding
  quarter in the same year and reporting scope. Gaps are not bridged.
- **Annualized NCO rate:** quarterly NCO divided by adjacent-quarter average
  segment exposure, multiplied by four. It is an observed accounting loss rate,
  not a separately estimated probability of default or loss given default.
- **CRE:** construction, multifamily, and nonfarm nonresidential categories.
  The switch from historical aggregates to successor components occurs at the
  2008Q1 annual reset. All required components must be available.
  [Taxonomy and source bridge](../metadata/cre_flow_definition_sources.md).
- **Mortgage:** closed-end 1–4 family residential lending. Revolving/open-end
  exposures are excluded to align stocks and flows.
  [Definition sources](../metadata/mortgage_definition_sources.md).
- **Allowance coverage:** allowance divided by bank total noncurrent loans.
  A bank-level ratio is not relabeled as a segment delinquency measure.
- **Tier 1:** mapped regulatory Tier 1 capital and RWA; the ratio is reconciled
  separately from book equity/assets. Losses/Tier1 measure modeled burden.
- **Units:** Call Report monetary amounts and saved stress losses are USD
  thousands. Divide by 1,000,000 to display USD billions. Rate decimals and
  macro series percentages are distinct; consult their configuration.

## Timing and controls against information leakage

Bank filings are conservatively treated as available 45 calendar days after
quarter end. Macro series are selected at the earlier report-period quarter
end. GDP and unemployment use available ALFRED vintages; configured final-vintage
fallbacks are lagged for availability. Model construction must not apply the
same lag twice. The fallback is still revised history, so the evaluation is not
a fully real-time vintage backtest. See the
[release calendar](../metadata/macro_release_calendar.csv) and
[vintage limitation](../metadata/macro_vintage_limitation.md).

Forecast eligibility uses available predictors; scoring additionally needs the
realized target. Models are compared on identical scoring keys. Recursive
historical checks keep current jump-off bank controls fixed and retain continuous
paths when subsequent realized outcomes are unavailable.

## Source audit and unresolved coverage

The [manual source audit](../metadata/manual_source_audit.csv) traces 100 selected
observations to archive members, raw YTD values, quarterization, and panel values.
It is separate from deterministic formula checks. Gross charge-offs and recoveries
are reconciled separately against bank totals; mapped segments are not assumed
to represent every loan category.

Two bounded gross-flow rows remain under review in the
[reconciliation register](../metadata/nco_reconciliation_review.csv). Unsupported
FFIEC 051 detail is retained as 60 unavailable segment rows. Some earlier FFIEC
031 CRE/Mortgage rates lack verified same-scope detail. Missing values are not
zero-filled, and averages/lags are not carried across unsupported gaps.

Source limitations and failed model diagnostics are retained because they affect
which comparisons and risk uses are defensible.
