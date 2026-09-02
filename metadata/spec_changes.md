# Research-specification changes

The Batch 2 primary specification was frozen on 2026-09-02 before running the
Batch 2 estimator.  Record every subsequent change below; do not overwrite this
entry after observing model results.

| Timestamp | Original specification | New specification | Reason | Changed after seeing results? |
| --- | --- | --- | --- | --- |
| 2026-09-02 | OOS windows beginning 2005 | Expanding OOS windows beginning 2017 (as specified in `configs/model_specs.yaml`) | The real Batch 1 model interface has complete NPL-control coverage beginning in 2017; the prior first two windows have zero complete observations. This was diagnosed before any AR, FE, SPJ, or CRE model result was run. | No |
| 2026-09-02 | `RCON/RCFD1403`-based NPL control and OOS windows beginning 2017 | FDIC BankFind `NCLNLS / LNLSNET` bank-level noncurrent-loan control and original 2005 OOS windows | The real Call Report field available from 2017 is total nonaccrual, not total noncurrent loans. FDIC Financials supplies the correctly defined bank-level numerator and denominator from 2005; the historical coverage and definition were verified before re-estimation. | No |
