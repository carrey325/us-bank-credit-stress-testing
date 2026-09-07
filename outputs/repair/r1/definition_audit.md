# R1 regulatory-definition audit

Status: `PASS` for R1 data-definition and panel use. The machine-readable
evidence register is `metadata/field_mapping_evidence.csv`.

## Determinations

- Item 2746 is excluded from secured CRE exposure. The Federal Reserve MDRM
  describes it as financing of real-estate activities carried in C&I/other-loan
  items and explicitly excludes loans secured by real estate, including 1415,
  1460, and 1480.
- FFIEC 041 CRE exposure is 1415 + 1460 + 1480 through 2007Q4. From 2008Q1 it
  is F158 + F159 + 1460 + F160 + F161. The overlap visible in 2007 archives is
  not double-counted.
- FFIEC 031 CRE and closed-end Mortgage use consolidated RCFD detail only from
  2013Q2, the first retained archive with the required component sets. Earlier
  031 observations are unavailable rather than constructed from domestic RCON
  stocks and consolidated RIAD flows.
- FFIEC 031 C&I requires both 1763 and 1764. FFIEC 041 uses reported aggregate
  1766. Actual form is read independently from each archive's POR member.
- RSSD 962966 filed as Golden Pacific Bank, N.A. on FFIEC 051 in all 20
  quarters from 2017Q1 through 2021Q4. R1 has no independently verified 051
  segment mapping, so those filings remain as 60 explicit segment placeholders
  with form, date, POR identity, and an unsupported-form reason. No financial
  value is imputed, and the placeholders prevent lag construction from bridging
  the five-year reporting-form interval.
- Mortgage remains closed-end 1-4 family first and junior liens. Revolving/open
  end item 1797 is excluded.
- Total nonaccrual remains a bank-level fallback, never a segment NPL. Allowance,
  Tier 1 capital, RWA, and separately reported Tier 1 ratio remain control
  mappings with form-specific variants; no new accounting model is introduced.

## Independent evidence

Official form/MDRM definitions establish meaning, dates, form, and reporting
scope. Retained raw archive description rows and raw numeric cells independently
establish which fields were present and what was reported. Production mapping
logic is not treated as its own reference answer.

## Units and timing

Monetary amounts are USD thousands. Quarterly NCO rate is a decimal; annualized
NCO rate is four times that decimal; display percent is 100 times the annualized
decimal. Negative NCO is retained. YTD differencing requires the immediately
preceding quarter within the same year and filing form. Average exposure requires
adjacent same-scope quarters and is suppressed at marked merger discontinuities.

## Explicit limitation

The retained raw snapshot cannot support same-scope 031 CRE or Mortgage rates
before 2013Q2. This range is `UNAVAILABLE`, not zero and not silently replaced.
FFIEC 051 segment measures are likewise explicitly unavailable pending a
separate independently evidenced mapping; this R1 repair does not claim 051
support.
