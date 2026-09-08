# Post-R3 Conditional R4 Scope Decision

Decision basis: user-selected Option A (minimal R3 plus conditional R4), the approved R3 artifact checkpoint `daabd4d52f8d2d3039e1ef116197adde5954cacf`, and `outputs/validation/model_use_registry.json`.

## Authorized formal stress models

- `ar_mean`, C&I: conditional-mean stress `ALLOWED`.
- `ar_mean`, CRE: conditional-mean stress `ALLOWED`.
- `dynamic_fe`, C&I: conditional-mean stress `ALLOWED`, but retain its R2 weak-incremental-performance limitation and report it as a limited challenger/sensitivity rather than proof of superiority.

## Excluded from formal stress results

- `dynamic_fe`, CRE: `DIAGNOSTIC_ONLY`; do not include it in formal rankings or headline stress results.
- Every quantile model: one-step diagnostic use only; do not create formal recursive stress paths, cumulative-loss quantiles, or tail rankings.
- Bayesian, residual-calibration expansion, multi-period tail distributions, Mortgage model expansion, market validation, machine learning, and a full capital roll-forward remain deferred.

## Required limited R4 work

1. Reuse the manifest-backed Fed 2026 baseline and severely adverse inputs and the R2 time/feature transformation contract; validate scenario provenance, units, lags, and boundary levels.
2. Rebuild 2026Q1–2028Q1 nine-quarter conditional-mean paths only for the authorized model/segment pairs above. Keep every quarterly state and input lineage.
3. Calculate static-exposure quarterly losses using the documented annualized-rate conversion. Report modeled credit-loss burden relative to starting Tier1, not a complete capital depletion or CET1 path.
4. Rebuild CRE grouping, mechanical equal-loss-rate exposure decomposition, negative-NCO floor sensitivity, and only the existing lightweight lambda/exposure/partial-shock sensitivities where inputs remain valid.
5. Keep diagnostic outputs separate from formal results. If a required input or gate fails, produce an explicit unavailable/limitation result instead of forcing a ranking.
6. Reject stale R1/R2/R3 models, mappings, residuals, or hashes at the formal reporting entry point.
7. Rebuild only supported final T1–T5/report/README/resume metrics, add `outputs/reporting/errata.md`, and use null plus reason for unavailable metrics. State RQ1–RQ4 results without exceeding the approved evidence.
8. Record unit, integration, artifact-consistency, and true end-to-end evidence separately. Do not claim end-to-end reproduction unless the manifest-backed chain actually runs.

R4 is a bounded closure and delivery stage. It must not reopen R1–R3 or broaden the research program.
