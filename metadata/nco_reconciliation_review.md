# R1 open NCO reconciliation review

The repaired core panel leaves 2 of 2,685 evaluable bank-quarters in
`REVIEW_REQUIRED`. These are isolated reported gross-flow inconsistencies, not
a form/date-wide mapping failure. They remain visible and are not forced to
pass or added to the exception allow-list.

| Bank ID | Quarter | Excess gross flow (USD thousands) |
|---|---|---:|
| 197478 | 2013Q2 | recovery 638 |
| 413208 | 2021Q4 | charge-off 506 |

Direct inspection of each current and immediately preceding retained FFIEC
RI-B archive member confirmed the total and every mapped CRE/C&I/Mortgage YTD
value used in the comparison. Neither row is caused by a missing required
component. Because the three mapped portfolios are subsets of all loans, their
gross flows are tested only as an upper bound against reported totals; no claim
is made that segment NCO must equal total NCO.

One separately documented 2012Q4 source-filing inconsistency remains in
`metadata/nco_reconciliation_exceptions.csv`. The two rows above are not
silently promoted to that status without additional independent evidence.
