# Batch 4 Fed stress results

- Final stress universe: 14 banks, each with complete CRE and C&I 2025Q4 states.
- Official scenarios are the Federal Reserve's 2026 final baseline and severely adverse domestic CSVs; lambda and partial shocks are clearly labelled researcher sensitivities.
- Primary capital result is cumulative credit loss / starting Tier 1 capital, not a Federal Reserve CET1 projection. Annualized NCO rates are divided by four; the non-negative floor applies only to dollar-loss aggregation and not to the recursive NCO state.
- 2026Q1 bank controls use the actual 2025Q4 current state and remain static. GDP/unemployment scenario features first affect 2026Q2, while final-vintage fallback features first affect 2026Q3 because Batch 2 applies their documented availability lag and the model then applies its own lag; `macro_predictor_timing.csv` records all sources.
- Dollar-loss floor use: 632 of 4032 path observations; see `loss_rate_floor_qa.csv`. Mortgage attribution is unavailable, not zero-filled, because no approved mortgage stress model exists.
- Bayesian ranking is unavailable because Batch 3 recorded no usable posterior forecasts; it is not imputed.
