# Batch 3 successful run

- Unified OOS forecasts: 14,622
- Mean-metric rows: 24
- Tail-metric rows: 112
- Recursive pseudo-stress forecasts: 11,304
- Bayesian status: explicit fallback; no posterior forecasts included.
- Figures: six required OOS/pseudo-stress figures in `outputs/validation/figures/`; the Bayesian panel is explicitly labelled unavailable if fallback is active.
- The pseudo-stress path uses realised macro history and recursive NCO; future bank controls are held at their last pre-window values.
- `pseudo_stress_metrics.csv` reports quantile pinball loss and empirical/nominal exceedance rates alongside mean-error metrics. Recursive CRE Q0.90 is not historically calibrated; its differing pre-specified window results show recursive-path instability. GFC: severe undercoverage (296/443 exceedances, 66.8% observed versus 10.0% nominal; pinball loss 0.08928); COVID: extreme overprediction (1/241 exceedances, 0.4% observed versus 10.0% nominal; pinball loss 0.01101); 2022+ high-rate/CRE: instability/mild undercoverage (63/457 exceedances, 13.8% observed versus 10.0% nominal; pinball loss 0.06346). Q0.90 remains the pre-specified downstream tail model where required, but is not validated by these historical recursive paths.
