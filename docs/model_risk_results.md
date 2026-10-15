# Model-risk extension: retained run and findings

Run `mrm-20261015-final`, code checkpoint `f330c86`. All numerical results below
come from the separate [compact evidence bundle](../results/model_risk/manifest.json).
The original portfolio evidence is unchanged. See [method and commands](model_risk.md)
for reproduction and interpretation.

## Independent validation and remediation

- 41,720 historical forecast rows were compared with separately reconstructed
  fitted states. No mismatches at absolute tolerance 1e-10 and relative tolerance
  1e-8; maximum absolute difference was 1.39e-17.
- The historical 507 crossing rows were independently reproduced. Existing
  rearrangement reduced crossings to zero while retaining raw values, keys and
  targets. The structural finding is closed; predictive adequacy is separate.
- All 48 reconstructed quantile design matrices were full rank; the maximum
  reported condition number was 1,476.37. This is reconstructed diagnostic evidence,
  not a claim that original fitted objects survived the historical run.
- On pooled common OOS observations, the gradient-boosting mean challenger's RMSE
  was 6.82% below AR for C&I (1,525 rows) and 2.65% below AR for CRE (1,264 rows).
  These are descriptive point comparisons, not significance or stress-authorization
  claims. Ridge, persistence, all windows, raw/post-rearrangement quantile scores
  and coverage diagnostics remain in the evidence tables.

Sources: [validation summary](../results/model_risk/validation_summary.json),
[challenger scores](../results/model_risk/challenger_scores.csv),
[crossing finding](../results/model_risk/crossing_finding.json),
[design and fit diagnostics](../results/model_risk/crossing_diagnostics.csv).

## Conditional cumulative C&I losses

31 banks, nine quarters, 20,000 paths per model/scenario, seed 772. The table
shows **USD billions**, converted from the saved USD-thousands results. Parameters,
2025Q4 exposures and controls are fixed. Quarterly losses use the nonnegative floor;
unfloored results and 99% tails are also retained.

| Model | Fed center | Mean | 95% VaR | 95% ES |
| --- | --- | ---: | ---: | ---: |
| AR benchmark | Baseline | 5.9013 | 11.1136 | 12.7010 |
| AR benchmark | Severely adverse | 5.9013 | 11.1136 | 12.7010 |
| Dynamic FE limited challenger | Baseline | 3.5145 | 6.5649 | 7.6240 |
| Dynamic FE limited challenger | Severely adverse | 12.4639 | 16.4629 | 17.6388 |

AR has no macro predictors, so its two distributions coincide under common random
numbers. Simulated means need not equal deterministic plug-in totals because
residual uncertainty and the aggregation floor change expected losses. Zero-shock
paths independently reproduced the archived deterministic rates for both models
and both scenarios. The fitted macro VAR spectral radius was 0.96656.

Sources: [risk summaries](../results/model_risk/risk_summary.csv),
[deterministic replay](../results/model_risk/deterministic_replay.csv),
[simulation diagnostics](../results/model_risk/simulation_diagnostics.json).

## Open model-use limitations

The distributions remain **conditional research diagnostics, not validated
predictive distributions**. No occurrence probabilities are assigned to the Fed
centers, and losses are not a capital roll-forward.

Historical nine-quarter bank interval coverage is inadequate in several windows.
For dynamic FE, the nominal 90% interval covered 0%, 43.75% and 78.95% of the scored
banks in windows 1, 2 and 4 respectively. Window 3 contains only eight quarters
and is explicitly not evaluated at nine quarters. These diagnostics condition on
realized available macro inputs and score only complete realized bank paths;
sample sizes and exclusions are retained.

The unbounded macro generator produced unemployment outside 0–100% in approximately
0.0894% of baseline path-quarter draws and negative BBB spreads in 1.8728%. No
clipping or path deletion hides these events. Further model development would
be needed before predictive use. Fixed parameters, final-vintage macros,
in-sample residual calibration, static balance sheets and residual dependence
not captured by the common factor remain material limitations.

Sources: [historical cumulative diagnostics](../results/model_risk/historical_nine_quarter_diagnostics.csv),
[path QA](../results/model_risk/path_qa.csv),
[status and limitations](../results/model_risk/stochastic_summary.json).

## Verification

- Compact checkout suite: 129 passed, 8 historical-artifact integration skips.
- With read-only archive copies restored in the isolated worktree: **137 passed**.
- Independent full-run rescore/retest and portfolio-tail recomputation passed.
- All 17 extension evidence files and the original 10 evidence files verified.
- Fresh-context review found a historical bootstrap population-centering mismatch;
  it was fixed with a shared helper and a regression test, then all retained
  results were regenerated. No unresolved critical or important review findings.
