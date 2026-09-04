# Batch 1 data-quality report

- Standard observations: 88,772
- Derived observations: 8,145
- Core banks: 33
- Field-mapping rows: 64
- Duplicate standard bank/date/raw-code keys: 0
- Negative NCO observations retained: 1856
- FDIC merger quarters flagged: 519
- Asset-jump quarters flagged: 72
- Manual formula-audit failures: 0

## Definitions

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
- NOT_EVALUABLE_MISSING_FLOW: 1
- PASS_SUBSET_GROSS_FLOWS: 2,711
- REVIEW_REQUIRED: 1
- Open review items: 1; see `metadata/nco_reconciliation_review.md`.

## Capital reconciliation

- Formula: mapped Tier 1 capital / mapped risk-weighted assets versus the separately reported Tier 1 risk-based capital ratio.
- Absolute tolerance: 1 basis point; ratios carrying a `%` suffix in the CDR files are normalized to decimal fractions before comparison.
- Evaluable bank-quarters: 2,715/2,715 (100.00%).
- Within tolerance: 2,715/2,715 (100.00%) when evaluable.
- PASS_WITHIN_TOLERANCE: 2,715

## Mapped raw-field presence

- 2005-03-31: 36 mapped raw codes
- 2010-03-31: 41 mapped raw codes
- 2020-03-31: 50 mapped raw codes
- 2025-12-31: 50 mapped raw codes

## Limitations

- The historical Call Report taxonomy has genuine reporting-detail changes. Missing segment detail remains missing; it is never filled with zero.
- FDIC history events are branch-granular and collapsed to bank-quarter merger flags; no virtual-bank reconstruction is claimed.
- `metadata/manual_source_audit.csv` records the independent raw-archive source-document sample; the deterministic audit is retained as a separate formula control.

## Direct source-document audit

- Fixed random sample: 100 bank-segment-quarters (seed 772).
- Direct FFIEC archive-member/raw-value to standard-layer matches: 100/100.
- Recomputed quarterly NCO to panel matches: 100/100.
- Source-audit failures: 0.
- This sample is evidence for the audited observations, not exhaustive proof of every reporting-detail change.
