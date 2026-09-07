# Minimal R3 run

- Run: `r3-20260907-minimal`; R2 input: `r2-20260907T194522Z`.
- Validation: `PASS`; quantile fits converged: `True`.
- Q0.50/Q0.75/Q0.90 are evaluated one step ahead against same-tau AR quantiles on common scoring keys.
- Historical GFC/COVID/high-rate paths use frozen pre-window bank controls; generation and scoring are separate.
- Recursive Q0.90 is sensitivity only. Multi-period tail distribution, residual calibration, and Bayesian work are not evaluated.
