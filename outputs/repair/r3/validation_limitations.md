# Minimal R3 validation limitations

- R2's negative findings are preserved: Dynamic FE improved equal-observation RMSE in 1/8 comparisons, and CRE amplification was not supported.
- Bayesian validation, Q0.95/Q0.99, ML challengers, static-versus-rolling residual calibration, and multi-period density simulation are `NOT_EVALUATED`.
- Q0.50-Q0.90 is a 40% band. No residual-calibrated two-sided 90% interval was regenerated.
- One-step quantiles are diagnostic only; zero exceedances are not interpreted as success. Raw and rearranged forecasts are both retained.
- Independently fitted quantiles crossed in 507 model-family/window/segment row instances before rearrangement; this is retained as instability evidence.
- Recursive mean paths condition on realized macro paths and frozen jump-off bank controls. They are plug-in paths, not asserted exact expectations.
- Fixed-Q0.90 recursive paths are sensitivity diagnostics only. No cumulative-loss Q0.90 or multi-period tail distribution was computed.
- Historical scoring uses available realized outcomes, while generation remains continuous when outcomes are unavailable. GFC training has few independent quarterly time points despite its cross-section.
- One-step post-rearrangement Q0.90 evaluation contains 5578 scored bank-quarters across reported segment-windows; window-level exceedance counts and rates are in `tail_metrics.csv`.
