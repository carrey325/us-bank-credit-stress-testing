# R3 prediction target dictionary

These targets are not interchangeable. Fixed-quantile recursive feedback is never a calibrated multi-period tail distribution.

## `one_step_conditional_mean`

One-quarter-ahead conditional mean point forecast.

status=EVALUATED

## `one_step_q90_upper_quantile`

One-quarter-ahead upper conditional Q0.90.

status=EVALUATED, nominal_coverage=90%, nominal_exceedance_rate=10%

## `one_step_q50_q90_band`

Band between one-step Q0.50 and Q0.90; not a two-sided 90% interval.

status=EVALUATED, nominal_coverage=40%

## `residual_calibrated_two_sided_90_interval`

Two-sided residual-calibrated interval, distinct from Q0.90.

status=NOT_EVALUATED, nominal_coverage=90%

## `conditional_mean_recursive_path`

Plug-in recursive point path conditional on a supplied macro path; not asserted to be an exact expectation.

status=EVALUATED

## `multi_period_cumulative_loss_q90`

Q0.90 of a joint multi-period cumulative-loss distribution; fixed-Q0.90 feedback is not this target.

status=NOT_EVALUATED, nominal_coverage=90%
