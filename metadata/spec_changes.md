# Research-specification changes

The Batch 2 primary specification was frozen on 2026-09-02 before running the
Batch 2 estimator.  Record every subsequent change below; do not overwrite this
entry after observing model results.

| Timestamp | Original specification | New specification | Reason | Changed after seeing results? |
| --- | --- | --- | --- | --- |
| 2026-09-02 | OOS windows beginning 2005 | Expanding OOS windows beginning 2017 (as specified in `configs/model_specs.yaml`) | The real Batch 1 model interface has complete NPL-control coverage beginning in 2017; the prior first two windows have zero complete observations. This was diagnosed before any AR, FE, SPJ, or CRE model result was run. | No |
