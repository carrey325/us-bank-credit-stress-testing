# Batch 3 successful run

- Unified OOS forecasts: 14,622
- Mean-metric rows: 24
- Tail-metric rows: 112
- Recursive pseudo-stress forecasts: 11,304
- Bayesian status: explicit fallback; no posterior forecasts included.
- Figures: six required OOS/pseudo-stress figures in `outputs/validation/figures/`; the Bayesian panel is explicitly labelled unavailable if fallback is active.
- The pseudo-stress path uses realised macro history and recursive NCO; future bank controls are held at their last pre-window values.
- `pseudo_stress_metrics.csv` reports quantile pinball loss and empirical/nominal exceedance rates alongside mean-error metrics. Recursive CRE Q0.90 is not historically calibrated; its differing pre-specified window results show recursive-path instability. GFC: severe undercoverage (363/443 exceedances, 81.9% observed versus 10.0% nominal; pinball loss 0.09040); COVID: extreme overprediction (2/241 exceedances, 0.8% observed versus 10.0% nominal; pinball loss 0.01165); 2022+ high-rate/CRE: severe undercoverage (94/457 exceedances, 20.6% observed versus 10.0% nominal; pinball loss 0.05824). Q0.90 remains the pre-specified downstream tail model where required, but is not validated by these historical recursive paths.
