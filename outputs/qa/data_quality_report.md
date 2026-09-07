# Batch 1 data-quality report

- Standard observations: 95,252
- Derived observations: 8,145
- Core banks: 33
- Field-mapping rows: 73
- Duplicate standard bank/date/raw-code keys: 0
- Negative NCO observations retained: 1967
- Suppressed incomplete segment gross flows: 60
- FDIC merger quarters flagged: 561
- Asset-jump quarters flagged: 72
- Manual formula-audit failures: 0

## Definitions

- CRE uses reported aggregate RIAD3582/3583 and RIAD3590/3591 through 2007Q4. From 2008Q1, construction is RIADC891+C893 / C892+C894 and nonfarm nonresidential is RIADC895+C897 / C896+C898; multifamily RIAD3588/3589 remains continuous.
- A segment gross flow is emitted only when every required component is present and quarterized; incomplete component sets remain missing rather than becoming partial flows.
- Mortgage is closed-end 1-4 family residential lending only: RC-C RCON/RCFD5367 + 5368 and RI-B RIADC234 + C235 - C217 - C218. Revolving/open-end RCON/RCFD1797 is excluded.
- Segment NPL is unavailable in a stable mapping. `bank_total_npl`, `bank_total_npl_ratio`, and their lags are bank-level fallback controls; `segment_npl_rate` is deliberately missing rather than total NPL divided by segment exposure.
- `tier1_capital` and reported `tier1_ratio` use Schedule RC-R fields; `computed_tier1_ratio` is Tier 1 capital divided by mapped RWA. `equity_capital` and `equity_to_assets_ratio` are separately named book-equity measures.
- `allowance_coverage` equals allowance / bank total noncurrent loans (also named `allowance_to_total_npl`), not allowance / total loans.

## NCO reconciliation rule

- CRE, C&I, and mortgage are mapped loan segments, not the entire Call Report loan portfolio; their net NCO is therefore not required to equal reported total NCO.
- For bank-quarters with all four gross-flow values, mapped charge-offs and recoveries must each be no more than reported total plus 50 thousand dollars.
- A downward YTD revision explains only the corresponding gross-flow excess when the reported total for that same flow is revised downward. Unrelated or mapped-component revisions remain REVIEW_REQUIRED.
- A directly verified source-filing inconsistency may be explained only when it is listed in `metadata/nco_reconciliation_exceptions.csv`; it remains visible in the reconciliation output.
- EXPLAINED_SOURCE_FILING_INCONSISTENCY: 1
- EXPLAINED_YTD_RECLASS_GROSS_FLOW: 1
- NOT_EVALUABLE_MISSING_FLOW: 30
- PASS_SUBSET_GROSS_FLOWS: 2,681
- REVIEW_REQUIRED: 2
- Open review items: 2; see `metadata/nco_reconciliation_review.md`.

## Capital reconciliation

- Formula: mapped Tier 1 capital / mapped risk-weighted assets versus the separately reported Tier 1 risk-based capital ratio.
- Absolute tolerance: 1 basis point; ratios carrying a `%` suffix in the CDR files are normalized to decimal fractions before comparison.
- Evaluable bank-quarters: 2,695/2,715 (99.26%).
- Within tolerance: 2,695/2,695 (100.00%) when evaluable.
- NOT_EVALUABLE_MISSING_INPUT: 20
- PASS_WITHIN_TOLERANCE: 2,695

## Mapped raw-field presence

- 2005-03-31: 42 mapped raw codes
- 2010-03-31: 48 mapped raw codes
- 2020-03-31: 59 mapped raw codes
- 2025-12-31: 59 mapped raw codes

## Limitations

- The historical Call Report taxonomy has genuine reporting-detail changes. Missing segment detail remains missing; it is never filled with zero.
- FDIC history events are branch-granular and collapsed to bank-quarter merger flags; no virtual-bank reconstruction is claimed.
- `metadata/manual_source_audit.csv` records the independent raw-archive source-document sample; the deterministic audit is retained as a separate formula control.

## Core-universe primary-source review

- Reviewed legal entities: 42; current eligible core banks: 33.
- Review input: `metadata/specialized_business_review.csv`; the screen is fail-closed for candidates lacking a dated primary-source review.
- Reviewed prohibited classifications: credit-card=5; auto-finance=1; custody/asset-servicing=1; broker-dealer/trading=0.
- Specialized exclusions: SYNCHRONY BANK (credit_card_dominant); AMERICAN EXPRESS NB (credit_card_dominant); NORTHERN TRUST CO (custody_asset_servicing_dominant); TD BANK USA NATIONAL ASSN (credit_card_dominant); BARCLAYS BANK DELAWARE (credit_card_dominant); COMENITY CAPITAL BANK (credit_card_dominant); ALLY BANK (auto_finance_dominant).
- Classification is applied to the FDIC legal entity; a parent or sibling affiliate's business is not imputed without primary-source support.

## Direct source-document audit

- Fixed reproducible sample: 100 bank-segment-quarters (seed 772), including required transition rows.
- Direct FFIEC archive-member/raw-value to standard-layer matches: 100/100.
- Recomputed quarterly NCO to panel matches: 100/100.
- Source-audit failures: 0.
- Deliberate CRE taxonomy-transition coverage: 6 observations across 3 quarters; 6/6 passed.
- POR-verified unsupported-form coverage: RSSD 962966 / Golden Pacific Bank, N.A., 20 FFIEC 051 quarters (2017Q1-2021Q4), retained as 60 explicit unavailable segment rows.
- This sample is evidence for the audited observations, not exhaustive proof of every reporting-detail change.
