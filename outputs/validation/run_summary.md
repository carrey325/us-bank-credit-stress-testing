# Batch 3 successful run

- Unified OOS forecasts: 14,622
- Mean-metric rows: 24
- Tail-metric rows: 112
- Recursive pseudo-stress forecasts: 11,304
- Bayesian status: explicit fallback; no posterior forecasts included.
- Figures: six required OOS/pseudo-stress figures in `outputs/validation/figures/`; the Bayesian panel is explicitly labelled unavailable if fallback is active.
- The pseudo-stress path uses realised macro history and recursive NCO; future bank controls are held at their last pre-window values.
- `pseudo_stress_metrics.csv` reports quantile pinball loss and empirical/nominal exceedance rates alongside mean-error metrics. Recursive CRE Q0.90 paths are unstable in COVID and 2022+; they are a tail-model limitation, not full recursive-stress validation.
