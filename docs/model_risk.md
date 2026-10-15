# Independent validation and stochastic credit-risk extension

This extension preserves the historical data definitions, four OOS windows,
R2/R3/R4 replay gates and published research snapshot. It adds process-separated
validation, a formal quantile-crossing retest and fixed-parameter C&I simulations.
It does not establish organizationally independent validation or regulatory approval.

The retained [results and open findings](model_risk_results.md) summarize the
real-archive run and link its compact evidence.

## Run the three stages

Install Python 3.11+ and `python -m pip install -e ".[test,modelrisk]"`.
The archive argument is the directory containing historical `data/` and
`outputs/` trees and their original validation sidecars. No downloads are needed.

```powershell
python scripts/freeze_and_validate.py --archive "<ARCHIVE_ROOT>" --run-id mrm-example
python scripts/retest_quantile_crossing.py --run outputs/model_risk/mrm-example
python scripts/simulate_credit_risk.py --run outputs/model_risk/mrm-example
python scripts/freeze_and_validate.py --verify-run outputs/model_risk/mrm-example
```

All stages reject existing destinations. A failed attempt retains `status.json`
or `failure.json`; use a new run ID/output name after correcting the cause. Never
edit sealed files or refresh hashes to suppress a failure. `--paths 500
--output-name stochastic-smoke` creates a separate smoke experiment. Defaults:
20,000 paths per model/scenario, 2025Q4 cutoff, nine quarters, four-quarter blocks,
seed 772. Configuration is in `configs/model_risk.yaml`.

```powershell
python scripts/freeze_and_validate.py --export-run outputs/model_risk/mrm-example --destination results/model_risk
python scripts/freeze_and_validate.py --verify-evidence results/model_risk
python scripts/export_results.py --verify
```

The last command verifies the original snapshot. Full-run verification checks
parent/child hashes, recomputes observation-level scores, repeats the structural
crossing retest and recomputes portfolio VaR/ES from path totals. Compact evidence
verification checks hashes only; it does not rerun models or Monte Carlo paths.

## Validation contract

- Inputs are copied byte-for-byte after historical sidecar verification.
  Manifests bind input hashes, configurations, source files and package versions.
- Historical forecasts and reconstructed fitted models are distinct objects;
  every prediction difference is retained. Linear states preserve feature order
  and bank intercepts; local joblib files preserve trained tree/Ridge pipelines.
  Load only trusted local joblib artifacts after verification: hashes are
  integrity checks, not signatures.
- Keys are bank, segment, forecast origin and target quarter, distinguished by
  window, model, quantile and version. Duplicate keys, conflicting outcomes,
  nonfinite predictions and hash mismatches fail closed.
- Independent scoring computes RMSE/MAE/Bias (`actual - prediction`), pinball,
  exceedance and Q50–Q90 coverage (nominal 40%). Comparisons use common scoring
  keys per estimand/window/version. Pooled results use individual observations.
  Missing targets affect scoring only. Empty comparisons and exclusions remain
  visible. Zero exceedances do not establish calibration.
- Persistence, Ridge and gradient boosting share the historical information set.
  Ridge alpha is selected from 0.1/1/10; tree depth from 1/2, with 100 estimators,
  0.05 learning rate and 10 minimum leaf observations. Three expanding temporal
  folds occupy the latter half of training quarters. Scaling and encoding are
  fitted inside each fold. Unknown-bank exclusions and all candidate scores are
  retained; direct prediction with an unknown bank fails. No OOS outcomes tune
  models. Trees use squared-error means and Q50/Q75/Q90 quantile objectives;
  both raw and rearranged forecasts are retained.

## Finding MRM-QC-001

The historical contract has 507 crossing prediction rows, counted once per
model/window/segment/key, not once per tau. Independently fitted quantiles lack
a joint order constraint. Convergence, iterations, feature counts and sample
support remain diagnostic evidence rather than asserted causes.

The existing row-wise increasing rearrangement remains the remedy. Independent
retesting checks complete quantile vectors, identical keys and targets, preserved
raw value multisets, zero remaining crossings, and agreement with historical
repaired forecasts. A structural closure does not close predictive calibration
findings. Reports include score changes and affected keys; targets never enter repair.

## Conditional C&I distributions

The historical 31-bank C&I universe, 2025Q4 exposures and bank controls are frozen.
AR and dynamic FE are reconstructed separately; zero-noise paths must reproduce
archived deterministic rates. Dynamic FE retains its limited-challenger status;
AR's absence of macro sensitivity remains visible. OOS challengers are not
automatically promoted into stress models.

GDP QoQ percent growth, unemployment percent, BBB spread and short rate in
percentage points use a standardized VAR(1). Rank deficiency, nonfinite inputs,
missing quarters or an unstable transition fail explicitly. Initial deviations
are zero. Deviations are added to each Fed center and mapped by the archived
source quarter: GDP/unemployment use one-quarter source delay; final-vintage
fallback series use two. No extra blanket lag is applied.

Bank residuals are standardized using training data. Their available-bank mean
forms a common factor when at least half the banks are observed. Bank loadings
and scales use available pairs; missing residuals stay missing. At least 20 bank
quarters and complete four-quarter blocks are required. Macro innovations and
the common factor are sampled together by quarter; bank-specific blocks are
independent conditional on that factor. The block population is recentered to
remove endpoint/availability weighting drift. Blocks never bridge gaps. Remaining
cross-bank idiosyncratic correlations are disclosed, not preserved by assumption.

Raw NCO feeds the next quarter, including negative values. Dollar loss is
`max(rate, 0) * exposure_thousands / 4`; unfloored totals are also retained. Banks
share macro/common shocks. Aggregate within each path before computing portfolio
VaR and ES; do not sum bank VaRs. Baseline and adverse distributions remain
separate, with no assigned occurrence probabilities.

VaR is the empirical inverse CDF. ES integrates the worst `1-alpha` probability
mass, including fractional boundary observations. Outputs include 95%/99% tails,
means, medians, half-sample sensitivities, mean MC standard errors and
100-bootstrap portfolio tail MC standard errors. These reflect sampling error,
not parameter uncertainty or model misspecification.

## Diagnostics and limits

All four historical windows have one-step residual intervals and macro errors.
Nine-quarter credit simulations condition on realized available macro paths and
freeze controls at each training endpoint. The eight-quarter 2020–2021 window
is explicitly not evaluated at nine quarters. Only banks with nine realized
outcomes enter cumulative scoring; other generated paths remain available.
These are conditional residual-layer diagnostics, not backtests of probabilities
assigned to Fed scenarios.

Limitations include final-vintage macros, in-sample residual calibration, fixed
parameters/balance sheets, limited support, remaining dependence and inadequate
cumulative interval coverage in some windows. The unbounded macro generator can
produce negative unemployment or BBB spreads; frequencies are reported without
clipping. Thus `integrity_status=PASS` coexists with
`calibration_status=LIMITED_NOT_VALIDATED_FOR_PREDICTIVE_USE`.

Full paths, model binaries and reports stay local under `outputs/`. Public compact
evidence has a separate manifest and does not replace `results/evidence/` or
`results/provenance.json`.
