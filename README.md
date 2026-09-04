# MF772 Bank Credit Stress Testing

## Problem

This project is a reproducible, public-data, top-down credit stress-testing framework for U.S. regional banks. It reconstructs quarterly segment-level net charge-off (NCO) rates and uses the approved Federal Reserve 2026 baseline and severely adverse scenarios to produce transparent credit-loss and loss-to-starting-Tier-1-capital estimates. It is not a bank-failure classifier, a trading strategy, a causal CRE study, or a reproduction of confidential FR Y-14 supervisory models.

## Data

The core unit is bank x loan segment x quarter. The generated historical panel contains 33 banks, 3 segments (CRE, C&I, and closed-end Mortgage), 84 quarters, and 8,145 observations. Inputs are official FFIEC Call Report bulk archives, FDIC BankFind records, and documented macroeconomic series. Raw source files are intentionally excluded from Git; manifests preserve source URLs, retrieval timestamps, and SHA-256 hashes.

The effective-dated regulatory mapping is in `metadata/field_mapping.csv`. Source and reconciliation caveats are retained in `metadata/` rather than silently repaired.

## Method

The project reconstructs quarterly NCO as charge-offs less recoveries divided by average segment exposure. It uses AR and dynamic fixed-effects mean models, split-panel-jackknife comparison, Q0.50/Q0.75/Q0.90 quantile models, historical pseudo-stress tests, and Fed 2026 scenario recursion. Primary capital output is cumulative credit loss divided by starting Tier 1 capital.

Batch 5 adds a documented rolling residual-bootstrap 90% interval fallback around out-of-sample Dynamic-FE forecasts. It is a model-risk layer, not a replacement credit-loss model. The adaptive interval uses only earlier OOS residuals; methodology and metrics are written to `outputs/model_risk/`.

## Key Results

All figures and numbers are generated from the saved pipeline outputs. The 2025Q4 CRE/C&I stress universe has 14 banks. In the committed mean-model comparison, AR has the lowest pooled OOS RMSE. Dynamic-FE remains the pre-specified structural stress model, so its result is not described as an RMSE improvement. Under the Fed severely adverse Dynamic-FE run, the high-minus-low CRE-to-Tier-1 tercile difference in mean capital depletion is 28.41 percentage points.

The rolling residual-calibrated intervals achieve 94.4% CI coverage and 92.1% CRE coverage over their post-seed OOS periods, versus 96.9% and 92.8% for the static residual-calibrated comparator. Rolling calibration increases crisis upper misses in this run (CI: 9 to 21; CRE: 27 to 31), so it does not achieve the desired crisis-underprediction reduction. These are empirical calibration results, not guarantees. See the final ten-page draft at `outputs/reporting/MF772_final_report_draft.pdf`.

## Reproducibility

Install the project dependencies, restore the manifest-backed raw inputs when needed, and run the checkpoints in order:

```powershell
python -m pip install -r requirements.txt
make raw
make standard
make panel
make qa
make models
make stress
make report
python -m pytest -q --basetemp .pytest-local
```

`make report` runs `scripts/run_batch5.py`, which regenerates final tables, figures, the report draft, resume metrics, and the reproducibility audit. The audit must report `PASS`; its detailed output is `outputs/reporting/reproducibility_audit.md`.

## Limitations

- One FFIEC source reconciliation item remains `REVIEW_REQUIRED`; it is not reclassified without evidence.
- Some macro variables use a documented final-vintage, one-quarter-lag fallback rather than a full real-time vintage feed.
- Bayesian posterior forecasts are unavailable under the documented environment fallback, so no posterior result is claimed.
- Recursive CRE Q0.90 is not historically calibrated across all three pre-specified pseudo-stress windows and is not presented as a validated tail forecast.
- Mortgage stress attribution is unavailable because no approved Mortgage stress model exists; it is never filled with zero.
- Market external validation is not completed because this checkout does not contain a verified bank legal entity -> BHC/parent -> listed ticker mapping. No name-based ticker match or market-validation claim was made.
