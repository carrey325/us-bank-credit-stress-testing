# MF772 Post-R2 Research-Scope Retrospective

Date: 2026-09-07

Selected scope: `Option A — MINIMAL_R3_THEN_CONDITIONAL_R4`, authorized by the user on 2026-09-07.

## Gate status

- R1 is approved at `f06531def118ce5cf5063180c21d07bcee5e5fc5`.
- R2 implementation is complete at `fff63c3608f896e8f74c06de8956956866999273`.
- The committed R2 state checkpoint is `ce667cfc5f04a1797b694e763dacb59689c87066`.
- Astra Extra High Reviewer decision for the final R2 checkpoint: `APPROVED`.
- Full R2 validation: 90 tests passed; 24 R2 sidecars validated with zero failures.

## Research findings that govern scope

- The repaired data and timing contracts pass their R2 gates.
- Dynamic FE improves equal-observation RMSE over AR in only 1 of 8 segment-window comparisons. Broad incremental predictive benefit is `NOT_SUPPORTED`.
- The corrected ex-post CRE interaction estimate is `-5.9863299e-06`, clustered SE `1.3113601e-05`, with 95% CI `[-3.1688988e-05, 1.9716329e-05]`. CRE amplification is `NOT_SUPPORTED`.
- SPJ remains diagnostic only.
- R2 does not authorize multi-period tail-distribution claims, stress rankings, or final reporting.
- Tail, stress, model-risk, reporting, and resume artifacts remain `INVALID_PENDING_REBUILD`.

## Scope decision options

### Option A — MINIMAL_R3_THEN_CONDITIONAL_R4 (recommended)

Run only the minimum R3 required by the Repair Control: fair one-step Q0.50/Q0.75/Q0.90 evaluation against a same-target baseline, correct exceedance accounting, minimum historical recursive-path checks, and the model-use registry. Do not add Bayesian work, model search, new ML families, or expanded calibration experiments. After R3, run a limited R4 only for uses explicitly permitted by the registry; if no model qualifies for conditional-mean stress use, deliver an honest limitation/unavailable report instead of rankings.

Rationale: data and methods are now reliable, but mean-model gain and CRE amplification are not supported. This follows the Repair Control's prescribed scope contraction without abandoning the remaining validation and delivery obligations.

### Option B — FULL_SPEC_R3_THEN_LIMITED_R4

Run the complete R3 scope currently written, including static-versus-rolling residual calibration and all specified historical diagnostics, then run R4 subject to the resulting model-use registry. Bayesian, automated search, new model families, and other explicitly deferred work remain excluded.

Tradeoff: produces richer validation evidence, but consumes more effort despite weak R2 evidence and must not be used to search for a favorable result.

### Option C — STOP_AFTER_R2

Accept R1/R2 as the end of this repair cycle, retain all downstream artifacts as invalid, and publish no refreshed tail validation, stress ranking, or final report.

Tradeoff: lowest additional effort, but the project remains without a rebuilt validation/use registry and without an updated final delivery.

## Router constraint

The user selected Option A. One minimal R3 Worker may start. R3 must complete and be reviewed before any R4 Worker is created; R4 remains conditional on the model-use registry.
