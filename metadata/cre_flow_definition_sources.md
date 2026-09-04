# CRE flow taxonomy and transition evidence

Batch 1 constructs CRE gross flows from the complete construction, multifamily,
and nonfarm nonresidential definitions in Schedule RI-B.

## Source-verified bridge

- Through 2007Q4, construction uses reported aggregate `RIAD3582` charge-offs
  and `RIAD3583` recoveries. The Federal Reserve MDRM states that beginning in
  2008Q1 item 3582 is derived as `RIADC891 + RIADC893`; item 3583 is analogously
  derived as `RIADC892 + RIADC894`.
- Through 2007Q4, nonfarm nonresidential uses reported aggregate `RIAD3590`
  charge-offs and `RIAD3591` recoveries. The MDRM states that beginning in
  2008Q1 item 3590 is derived as `RIADC895 + RIADC897`; item 3591 is analogously
  derived as `RIADC896 + RIADC898`.
- The split C891–C898 series begin in 2007Q1. The pipeline deliberately retains
  the continuously reported aggregate fields through 2007Q4 and switches to
  the complete split definitions at the 2008Q1 calendar-year reset, preventing
  overlap and avoiding any cross-MDRM YTD difference.
- Multifamily `RIAD3588` charge-offs and `RIAD3589` recoveries remain continuous
  across this transition.

Official references:

- [MDRM item 3582](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=3582)
- [MDRM item 3583](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=3583)
- [MDRM item 3590](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=3590)
- [MDRM item 3591](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=3591)
- [MDRM item C891](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C891)
- [MDRM item C895](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C895)

## Direct archive audit

`metadata/manual_source_audit.csv` forces two CRE observations from each of
2007Q4, 2008Q1, and 2008Q2 into its 100-observation sample. The 2007Q4 rows
trace the reported aggregates to their prior-quarter YTD values; the 2008Q1
rows trace every split component at the annual reset; and the 2008Q2 rows trace
every split component to its 2008Q1 predecessor. All six transition observations
pass raw-archive-to-standard and recomputed-flow-to-panel checks.

The panel suppresses a segment gross flow whenever any required MDRM component
is absent or cannot be quarterized; it never sums the remaining components into
a partial CRE flow.
