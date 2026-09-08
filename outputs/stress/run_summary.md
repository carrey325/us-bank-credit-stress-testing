# R4 limited conditional-mean stress rebuild

- Run: `r4-20260908-limited-delivery`; common stress universe: 31 banks.
- Formal baseline: AR mean for C&I and CRE. Limited sensitivity: Dynamic FE for C&I only. Dynamic FE CRE, all quantiles, Bayesian, Mortgage expansion, and multi-period tail claims are excluded.
- Paths cover 2026Q1--2028Q1 and retain recursive state, scenario predictors, source quarters, source types, static 2025Q4 exposure, and starting Tier1.
- `quarter_loss_thousands = annualized_nco_rate_decimal / 4 * exposure_thousands`. Reported ratios are modeled credit-loss burdens relative to starting Tier1, not capital depletion or CET1 changes.
- Severity monotonicity is diagnostic and is not forced. See `severity_monotonicity_qa.csv`.
