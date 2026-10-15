# Model risk extension — implementation ledger

Approved scope: independent frozen-artifact validation and quantile-crossing
retest for CRE/C&I; persistence, Ridge and gradient boosting challengers;
C&I-only nine-quarter simulations around separate Fed scenarios with fixed
parameters, correlated macro innovations and common-factor credit residuals.
Historical data definitions, R2/R3/R4 gates and published evidence stay intact.

## Delivery sequence

1. Immutable input bundles, independent scoring and model reconstruction.
2. Training-only time-series challenger selection and frozen model replay.
3. Finding/root-cause/remediation/independent-retest evidence.
4. VAR/common-factor block bootstrap, loss propagation, risk summaries.
5. Real-archive runs, report, regression suite and fresh-context review.

## Interface contract

Bundles contain a versioned manifest of relative paths and SHA-256 hashes.
Normalized forecasts use bank_id, segment, forecast_origin, target_period,
window, model, tau, version, actual, prediction. Mean tau is null. Frozen
linear models contain ordered predictors, coefficients and entity intercepts.
Tree/Ridge states are local joblib artifacts, hash-checked before loading.
Scoring imports no fitting or legacy scoring functions.

## Decisions and progress

- Baseline: 101 passed, 8 archived-artifact checks skipped; commit 22886c1.
- Native worktree creation cannot target this repository from the parent chat
  directory. Created an external Git worktree in Project Enhance instead.
- Historical fit objects do not exist. Preserve historical predictions and
  label every reconstructed state RECONSTRUCTED, with row-level differences.
- Macro timing follows existing per-variable source-quarter mapping: GDP and
  unemployment have one-quarter source delay; final-vintage fallback features
  have two-quarter delay. Do not add another blanket lag.
- All model-risk outputs are research diagnostics. Structural integrity PASS
  is distinct from predictive adequacy and authorization for use.

## Review focus

Hash/manifest trust boundaries; unavailable and conflicting outcomes; training
cutoffs in nested selection; block continuity with missing bank observations;
aggregation and empirical ES with ties and fractional tail probability.

## Completed implementation checks

- Tasks 1–3: frozen inputs, reconstruction, challengers and independent retest
  implemented. Real archive: 41,720 prediction comparisons, zero mismatches at
  rtol=1e-8/atol=1e-10; maximum absolute error 1.39e-17. Crossing 507 -> 0.
- Task 4: 20,000 paths per model/scenario completed for 31 C&I banks. Zero-noise
  replay matches historical deterministic output. Historical residual/macro and
  nine-quarter conditional diagnostics retained, including poor coverage.
- Ruling: use archive-bound macro predictor centers and source-quarter metadata
  instead of downloading/rebuilding Fed inputs — reproduces the precise approved
  boundary behavior and avoids silently revising historical definitions.
- Ruling: report unphysical macro draw frequencies without clipping; retain
  LIMITED_NOT_VALIDATED_FOR_PREDICTIVE_USE status, distinct from integrity PASS.
- Test evidence so far: 126 passed, 8 legacy integration skips; evidence export
  verification and fresh-context code review are the remaining delivery gates.
- Fresh-context review found one P2: historical residual blocks lacked the
  production population-centering step. Fixed with a shared centered_blocks
  function and endpoint-weighting regression (RED -> GREEN); regenerate evidence.
- Added reconstructed design rank/condition diagnostics to the finding record;
  these are explicitly labeled reconstructed rather than historical fit objects.
- Review rulings: regulatory suitability is not asserted; excluded Bayesian,
  mortgage and parameter work stays excluded; hash manifests are integrity checks,
  not adversarial signatures; poor coverage and inadmissible macro draws remain
  disclosed limitations. Eight legacy integration tests still need their exact
  original locations/artifacts and remain skipped; new real-run verification is separate.
- Final delivery: restored 202 archive output/derived files (8.8 MB) without
  overwriting existing files, enabling all historical integration tests.
  Full suite: 137 passed, no skips. Compact checkout: 129 passed, 8 skips.
- Final run mrm-20261015-final uses f330c86 source; full-run verification and
  independent tail recomputation passed. Exported 17 compact extension evidence
  files; all hashes verified, alongside all 10 original evidence files.
- Final review disposition: centering P2 fixed and tested; no unresolved critical
  or important findings. Retain the isolated branch and local full artifacts.
- Packaging check detected four JSON evidence blobs normalized by Git rather
  than preserving their hashed CRLF bytes. Added a model-risk evidence -text
  attribute and verified committed blobs plus a clean Git-archive checkout.
