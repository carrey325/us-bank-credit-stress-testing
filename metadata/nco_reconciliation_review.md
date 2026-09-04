# Open NCO Reconciliation Review Item

The generated `outputs/qa/reconciliation_summary.csv` retains one `REVIEW_REQUIRED` bank-quarter. It is not recoded as an explained exception because there is no causal YTD downward revision and it is not the separately documented 2012Q4 source-filing exception.

| Bank ID | Bank | Quarter | Gross-flow discrepancy | Status |
|---|---|---|---:|---|
| 197478 | EAST WEST BANK | 2013Q2 | mapped recoveries exceed reported total recoveries by $120 thousand | REVIEW_REQUIRED |

Direct inspection of the retained FFIEC RI-B archive members found the following YTD values (thousands):

- Reported total recoveries `RIAD4605`: 2,368 at 2013Q1 and 3,611 at 2013Q2, yielding quarterly reported recoveries of 1,243.
- Mapped CRE recoveries: `RIAD3589` 117→118, `RIADC892` 0→31, `RIADC894` 31→320, `RIADC896` 0→0, and `RIADC898` 257→998, yielding 1,062.
- Mapped closed-end Mortgage recoveries: `RIADC217` 7→307 and `RIADC218` 2→3, yielding 301.
- The mapped subtotal is therefore 1,363, or $120 thousand above the reported total. No total- or mapped-flow YTD decrease occurred in this quarter.

The pipeline retains the source values and the visible `REVIEW_REQUIRED` status. This item must not be converted to an explained source-filing exception without additional source evidence.
