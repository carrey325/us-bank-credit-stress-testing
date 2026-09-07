# MF772 Project Instructions

## Project

This repository implements the MF772 project according to the implementation plans under `workflow/`.

## Repair Cycle

The active incremental repair entry point is
`workflow/repair/00_Repair_Control.md`. Repair stages R1-R4 may make only the
cross-module corrections expressly authorized there and must run serially.
They do not reopen completed Batch 1-5 work unconditionally.

The project must be executed in the following dependency order:

1. Batch 1 — Data Engineering / Core Panel
2. Batch 2 — Macro / Core Models / CRE Integration
3. Batch 3 — Quantile / Bayesian Validation
4. Batch 4 — Fed Stress / Capital Depletion
5. Batch 5 — Model Risk / External Validation

Later batches must not be implemented before their dependencies are complete.

---

## General Execution Rules

For every Batch:

- Read this `AGENTS.md` first.
- Read the corresponding Batch plan in `plan/` completely before implementation.
- Inspect the relevant existing source code, tests, configuration, and data interfaces.
- Check `git status` before making changes.
- Preserve unrelated user changes.
- Stay strictly within the scope of the current Batch.
- Do not implement later Batch requirements early.
- Do not expand the refactor or redesign beyond what the current Batch requires.
- Prefer simple, reproducible, testable implementations over unnecessary abstraction.
- Reuse stable existing implementation whenever appropriate.
- Keep source code, tests, data, generated outputs, reports, and documentation clearly separated.

If a Batch explicitly requires only testing, documentation, validation, or analysis, do not add implementation beyond that scope.

---

## Batch Completion Standard

A Batch is complete only when all requirements in its plan have been satisfied.

Before declaring completion:

1. Run the validation and tests required by the Batch plan.
2. Fix issues introduced by the current Batch.
3. Perform at most one final reviewer/subagent review after implementation is substantially complete.
4. Address reviewer findings only when they belong to the current Batch scope.
5. Record the validation results.
6. Commit the completed Batch.
7. Confirm the working tree is clean, unless an explicitly documented exception exists.

Each Batch should end with one clear Git checkpoint commit.

Suggested history:

- baseline — Initialize MF772 project
- Batch 1 — complete
- Batch 2 — complete
- Batch 3 — complete
- Batch 4 — complete
- Batch 5 — complete

---

## Git Rules

Before starting a Batch:

- confirm the repository root;
- inspect `git status`;
- inspect the latest relevant commit;
- confirm the previous Batch is complete;
- preserve unrelated existing modifications.

During implementation:

- do not rewrite unrelated history;
- do not discard user changes;
- do not commit large generated datasets unless explicitly required;
- do not commit secrets, credentials, tokens, or private keys.

After completing a Batch:

- run required validation;
- commit the Batch;
- report the commit hash;
- leave the repository in a clean state when possible.

---

## Research and Modeling Integrity

This is a financial research / modeling project.

Do not fabricate or silently invent:

- datasets;
- observations;
- model estimates;
- empirical results;
- validation statistics;
- benchmark results;
- citations;
- external validation evidence;
- stress-test outcomes;
- capital results.

If required data, assumptions, methodology, or external evidence are unavailable or ambiguous, report the issue explicitly.

Do not silently substitute a different research question or modeling assumption merely to make the code run.

When an approximation or fallback is necessary:

1. state the limitation;
2. explain the approximation;
3. isolate it clearly in code/configuration;
4. avoid presenting approximate outputs as validated final results.

---

## Reproducibility

All analytical results should be reproducible from documented inputs and code.

Where applicable:

- use deterministic random seeds;
- document input data sources;
- document transformations and filters;
- separate raw/intermediate/final data;
- make model configuration explicit;
- avoid hard-coded machine-specific absolute paths;
- store environment or dependency information;
- ensure important tables, figures, and metrics can be regenerated.

Generated outputs should not become hidden dependencies for later Batches unless explicitly documented.

---

## Data Handling

Do not modify raw source data in place.

Prefer a structure such as:

```text
data/
  raw/
  interim/
  processed/

src/
tests/
outputs/
reports/
plan/
```

The exact structure may evolve according to the Batch plans.

Large datasets, temporary files, model artifacts, caches, and generated outputs should be excluded from Git when appropriate.

If a Batch defines a canonical schema, interface, panel, feature set, or dataset contract, later Batches must use that contract rather than creating incompatible parallel versions.

---

## Testing and Validation

Testing must reflect the current Batch requirements.

Where applicable, include:

- unit tests;
- schema checks;
- data-quality checks;
- regression tests;
- model sanity checks;
- deterministic reproducibility checks;
- validation against known benchmarks or externally specified expectations.

Passing code execution alone is not sufficient evidence that the financial or statistical methodology is correct.

Do not weaken tests merely to make the Batch pass.

---

## Scope Control

The current Batch plan is authoritative for implementation scope.

Do not:

- implement future Batch features;
- introduce unrelated frameworks;
- migrate technologies without necessity;
- perform broad cosmetic refactors;
- replace stable code simply because another design appears preferable;
- redesign project architecture unless required by the plan.

If the current plan conflicts with the existing implementation or with another Batch plan, stop and report the conflict instead of guessing.

---

## Reviewer / Subagent Rule

Each Batch may use at most one final reviewer/subagent review.

The reviewer should be invoked only after the Batch implementation is substantially complete.

Do not repeatedly create reviewers.

After review:

- fix valid findings that are within current Batch scope;
- document unresolved findings that belong to later Batches;
- do not expand scope solely to satisfy optional reviewer suggestions.

---

## Scheduler / Worker Contract

When this repository is being executed through a Scheduler:

- the Scheduler coordinates work only;
- the Scheduler should not implement project code;
- each Batch should be executed by a separate Worker thread;
- Batches must run strictly in dependency order;
- Batch N+1 must not begin until Batch N is confirmed complete.

Each Worker should finish with one of the following explicit statuses.

Successful completion:

```text
Batch N STATUS: COMPLETE

Summary:
...

Files Changed:
...

Validation:
...

Commit:
...

Remaining for Later Batches:
...
```

Blocked execution:

```text
Batch N STATUS: BLOCKED

Reason:
...
```

A Batch should not be treated as complete unless the Worker reports:

- `Batch N STATUS: COMPLETE`;
- validation results;
- a Git commit;
- any remaining later-Batch items.

---

## Blocking Conditions

Stop and report rather than guessing when continuation requires:

- changing the approved research objective;
- making an unresolved cross-Batch architecture decision;
- destructive data operations;
- unavailable required data;
- missing permissions or credentials;
- contradictory Batch requirements;
- materially ambiguous statistical or financial methodology;
- a decision that could invalidate downstream results.

Ordinary coding bugs, failing tests, or implementation difficulties inside the current Batch are not automatically blocking conditions and should normally be resolved by the Worker.

---

## Final Principle

Correctness, research integrity, reproducibility, and adherence to the Batch plan take priority over speed.

Complete the current Batch cleanly before moving to the next one.
