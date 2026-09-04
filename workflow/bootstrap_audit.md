# MF772 Bootstrap Takeover Audit

Audit time: 2026-09-04T00:26:45Z  
Repository: `F:\Python file\codex\MF772`  
Proposal: `proposal/MF772_Bank_Credit_Stress_Test_Proposal.pdf`  
Acceptance specifications: `workflow/Batch_1_Data_Engineering_Core_Panel.md` through `workflow/Batch_5_Model_Risk_External_Validation_Delivery.md`

## Executive determination

- `LATEST_FULLY_COMPLETED_BATCH: NONE` under the strict sequential acceptance gate.
- `FIRST_INCOMPLETE_BATCH: 1`.
- `FIRST_UNMET_ACCEPTANCE_CRITERION: Batch 1 DoD item 8 — manual audit has not completed human source-document review`.
- Batch 1 is substantially implemented and reusable; it is not zero-percent complete.
- Batch 2 independently satisfies its own ten DoD items and has a committed GFC-window amendment, but cannot be counted as sequentially complete while Batch 1's gate remains partial.
- Batch 3 has a substantial uncommitted implementation, unit tests, and partial outputs. Its outputs predate the Batch 2 GFC-window amendment and the required pseudo-stress/figures are absent.
- Batch 4 and Batch 5 have not started.

## Audit basis and safety checkpoint

- The Proposal was extracted and visually checked (title, executive summary, and methodology/fallback overview) in addition to text review.
- The five workflow Batch specifications were read in full. Their blobs exactly match the deleted tracked copies under `plan/`; the Proposal blob exactly matches the deleted tracked root copy. These are uncommitted relocations, not content rewrites.
- Both prior Codex tasks were checked before repository inspection. The Batch 2 task and Batch 3 task were not loaded/running; their last turns were terminal. No active prior Worker was modifying this repository.
- Current branch: `main`.
- Current HEAD: `3d6e281add10a66d9595f4884615bd337bacf749` (`Batch 2 amendment — restore GFC NPL control`).
- Recent history: `3d6e281` -> `0104915` -> `8885bbc` -> `8697871`.
- Local safety tag: `archive/pre-router-migration` -> `3d6e281add10a66d9595f4884615bd337bacf749`.
- Remotes: none configured. No push was attempted.
- The working tree was already dirty before this audit. Existing tracked deletions/modifications and all untracked Batch 3/workflow files were preserved.

## Git and data safety

Result: `GIT_HISTORY_CLEAN_FOR_MIGRATION`; do **not** mark `GIT_HISTORY_CONTAMINATED`.

- No `data/raw/**`, `data/standard/**`, `data/derived/**`, `.duckdb`, `.feather`, `.env`, credential file, downloaded archive, or detected private-key/high-risk secret value appears in reachable Git history.
- Two Parquet files are tracked: `outputs/models/ar/predictions.parquet` (575,357 bytes) and `outputs/models/dynamic_fe/predictions.parquet` (576,763 bytes). They are small derived model-result artifacts, not raw/standard/derived source data or large downloads.
- The largest reachable blob is the Proposal PDF at 1,505,309 bytes. No blob over that size was found.
- Local untracked/ignored research inputs are present and were not deleted: `data/raw` has 292 files / 665,384,148 bytes; `data/standard` has 1 file / 835,122 bytes; `data/derived` has 5 files / 1,688,336 bytes. None is tracked.
- Manifest verification against local files passed: FFIEC main 84/84, FFIEC recovery 84/84, macro 175/175, and FDIC noncurrent 33/33; zero missing files, SHA-256 mismatches, or recorded-size mismatches.
- Current `.gitignore` correctly blocks `data/raw/`, `data/standard/*.parquet`, and `data/derived/*.parquet`, but is incomplete for future safety: generic `*.parquet`, `*.duckdb`, `*.feather`, `.env*`, credential/key files, generic archives, and non-Parquet files under `data/standard/**` / `data/derived/**` are not blocked. This is a future `FIX`; it does not contaminate existing history.
- Recommended migration: `MIGRATION_MODE_A`. Preserve the existing clean history, first correct ignore coverage and commit only approved small artifacts, then connect/push to the private target repository. No remote was added during this audit.

## Current test status

- Command: `pytest -q --basetemp .pytest-tmp-bootstrap` (run through RTK).
- Result: `14 passed`.
- Coverage includes FFIEC flow quarterization, year reset, missing-prior handling, retained negative NCO, standard-layer missingness, mapping coalescence, FDIC bank-level NPL denominator, macro timing validation, common-sample OOS FE/AR, CRE interaction, quantile fitting, and tail metric labeling.
- This unit result does not substitute for missing human source-document validation, a fresh Batch 3 full run, Bayesian posterior diagnostics, or Batch 4/5 acceptance evidence.

## Batch 1 — Data Engineering / Core Panel

Overall: `PARTIAL`. The implementation, local data, metadata, tests, and most acceptance evidence are reusable.

### Explicit sample and mapping acceptance checks

- Core sample 30–40 and rejected-bank reasons: **PASS** — `metadata/institutions.csv` has 143 candidates and 33 core banks; `metadata/exclusion_log.csv` has 110 rejected rows with reasons.
- At least 40 regulatory raw fields: **PASS** — `metadata/field_mapping.csv` has 49 mapping rows and 48 unique raw codes.
- CRE/C&I/Mortgage exposure, charge-off, and recovery are constructible: **PASS with coverage limitation** — all three segments have exposure; CRE NCO has 2,714 non-null rows, C&I 1,605, and Mortgage 792. Missing historical reporting detail remains missing rather than zero-filled.
- Every mapped field has source and effective dates: **PASS** — all 49 rows have `source_reference` / `source_url`, `start_date`, and `end_date` fields populated as applicable.
- Field presence checked for 2005/2010/2020/2025: **PASS** — `outputs/qa/data_quality_report.md` records 25 / 30 / 42 / 42 mapped raw codes at the four audit dates.

### Definition of Done

1. Core sample at least about 25–30 banks: **PASS** — 33 core banks in `metadata/institutions.csv` and `data/derived/credit_panel.parquet`.
2. CRE/C&I/Mortgage all have usable exposure: **PASS** — each segment has 2,715/2,715 non-null exposure rows across 33 banks and 84 quarters in `credit_panel.parquet`.
3. Charge-off/recovery correctly quarterized: **PASS** — `quarterize_ytd()` in `src/bankstress/transform/flows.py`; six flow tests cover normal YTD, year reset, missing prior, revisions, and negative NCO.
4. True NCO reconstructed: **PASS** — `build_credit_panel()` sets `segment_nco = charge_off - recovery`; generated panel and 200 sampled formula traces agree.
5. Negative NCO not incorrectly deleted: **PASS** — 1,418 negative NCO observations remain; `test_recovery_exceeding_chargeoff_and_negative_nco_are_allowed` passes.
6. Merger quarter marked: **PASS** — `institution_lineage.csv` has 193 lineage rows; generated panel records 519 merger-quarter flags and 130 asset-jump flags.
7. Field mapping has version dates: **PASS** — `metadata/field_mapping.csv` has non-null effective-date columns; standardized rows carry `mapping_version=batch1-v1`.
8. Manual audit finds no systematic formula error: **PARTIAL** — `outputs/qa/manual_audit.csv` has 200/200 deterministic formula checks passing, but every reviewer note and `data_quality_report.md` explicitly say human source-document/facsimile review remains required. A deterministic self-check is not complete manual source validation.
9. Data-quality report can be reproduced: **PASS** — `write_qa()` in `src/bankstress/qa/report.py` regenerates reconciliation, manual trace, and report from standard/panel inputs; Batch 1 script calls it.
10. No obvious bank-ID mismatch: **PASS** — the panel has zero missing `bank_name` and zero missing `cert`; merge validation is `many_to_one` and all 33 bank IDs resolve.

### Hard-stop checks

- YTD not correctly quarterized: **PASS (not triggered)** — implementation and tests above.
- Cross-year field meaning unclear: **PASS with documented taxonomy limits** — dated mapping and four-era presence audit exist; limitations are recorded rather than silently imputed.
- Missing values filled with zero: **PASS (not triggered)** — `test_standard_layer_preserves_missing_not_zero` passes; outcome coverage counts retain missing values.
- Merger jumps untreated: **PASS (not triggered)** — event and asset-jump flags are present and the modeling sample excludes `merger_recent_flag`.
- Major segment NCO cannot be explained relative to regulatory totals: **PARTIAL / unresolved gate** — `outputs/qa/reconciliation_summary.csv` exists for 2,715 bank-quarters, but no tolerance, pass/fail rule, or signed explanation has been recorded. Mapped-vs-total NCO correlation is 0.660; median absolute difference divided by absolute reported total NCO is 0.736; 90.6% of rows have mapped absolute NCO no larger than total absolute NCO. The subset nature is plausible, but the acceptance conclusion is not closed.

Evidence checkpoint: commit `8885bbc`; local generated data and QA outputs are ignored and checksum-backed by manifests.

## Batch 2 — Macro / Core Models / CRE Integration

Overall: **PASS against its own DoD**, but **not counted as sequentially complete** until Batch 1's partial gate is closed. Implementation and results should be kept.

1. Macro merge has no future leakage: **PASS with declared fallback** — `build_macro_panel()` uses quarter-end ALFRED snapshots for GDP/unemployment and final-vintage values lagged one full quarter for five fallback series; `validate_release_calendar()` rejects future observations/availability. `metadata/macro_vintage_limitation.md` explicitly avoids claiming full real-time release dates.
2. Model spec frozen: **PASS** — `configs/model_specs.yaml` identifies the frozen specification; `metadata/spec_changes.md` records the GFC-window/NPL amendment before re-estimation.
3. AR baseline completes OOS: **PASS** — four expanding windows, two primary segments, eight metric rows, no missing metrics in `outputs/models/ar/oos_metrics.csv`.
4. Dynamic FE completes OOS: **PASS** — four windows/two segments and coefficient output in `outputs/models/dynamic_fe/`.
5. FE and AR use the same sample: **PASS** — `run_oos_models()` derives both from one `_eligible_frame`; test asserts equal sample counts and current metrics agree by window/segment.
6. Bias-corrected FE has a reliable implementation: **PASS** — split-panel jackknife implementation and 18-row `split_panel_jackknife.csv`; unit test passes.
7. CRE interaction runs: **PASS** — bank/quarter-demeaned regression produces five coefficient rows over 2,348 observations; unit test passes.
8. Exposure and interaction effects separately explained: **PASS** — `outputs/models/cre_interaction/result_status.md` distinguishes mechanical exposure from the interaction estimate.
9. EDA explains the main patterns: **PASS** — reproducible sample, segment, lead/lag, CRE-tercile tables and time-series figure exist under `outputs/eda/`.
10. Model failures logged instead of silently removed: **PASS** — `scripts/run_batch2.py` writes `outputs/models/run_failures.log` and re-raises exceptions.

Current local `model_panel.parquet`: 8,145 rows, 33 banks, 84 quarters (2005Q1–2025Q4). Current committed OOS windows begin in 2005 and include GFC-era training/testing support. Evidence checkpoints: `0104915` and amendment `3d6e281`.

## Batch 3 — Quantile / Bayesian / Validation

Overall: `PARTIAL`, uncommitted, and not accepted. Keep the implementation as a repair starting point; do not rerun from zero.

1. 0.50/0.75/0.90 quantiles can run: **PARTIAL** — `fit_quantile()` / `predict_quantile()` exist and the quantile unit test passes; 6,102 OOS prediction rows include all three quantiles. However those outputs use obsolete 2017-start windows rather than the amended 2005-start Batch 2 specification.
2. Tail metrics complete: **PARTIAL** — pinball, underprediction, crossing, coverage, width, and Winkler logic exists and tests pass; `tail_metrics.csv` has 88 rows, but it is tied to obsolete windows and has not been regenerated/validated against the current baseline.
3. Bayesian core converges or has explicit fallback: **PASS as fallback only** — all four diagnostic rows explicitly record `environment_fallback` because `BANKSTRESS_SKIP_BAYESIAN=1`; `result_status.md` excludes posterior results. No converged Bayesian result may be claimed.
4. All models use unified OOS: **FAIL** — the current Batch 3 comparison uses 2017-start windows, while committed Batch 2 outputs/spec use 2005-start windows; the Bayesian model is absent under fallback.
5. GFC/COVID/2022+ pseudo-stress reproducible: **FAIL** — implementation/config exists, but `outputs/validation/pseudo_stress.parquet`, methodology output, and all three stress figures are absent.
6. Quantiles are not judged by RMSE: **PASS** — quantile evaluation uses pinball loss and interval/tail diagnostics; `model_comparison.csv` contains mean-model metrics only.
7. Bayesian results include diagnostics: **PASS for fallback evidence** — `outputs/models/bayesian/diagnostics.csv` and `result_status.md` exist and clearly state no posterior was used.
8. Model comparison automatically generated: **PARTIAL** — `run_unified_oos()` writes it automatically, but the existing 24-row artifact is stale against the amended windows.
9. No hand-picked best window: **PASS in code** — `run_unified_oos()` loops all configured windows without selection logic.

Required figures: **FAIL** — none of the six Batch 3 figures exists.  
Git checkpoint: **FAIL** — no Batch 3 commit exists; source/config/tests/results are uncommitted.

## Batch 4 — Fed Stress / Capital Depletion

Overall: `NOT_STARTED`.

1. Fed scenario ingestion: **FAIL** — no Fed 2026 scenario dataset or ingestion module.
2. Nine-quarter recursive forecast: **FAIL** — no stress-path output.
3. Baseline and severe results: **FAIL**.
4. Segment attribution: **FAIL**.
5. Capital depletion: **FAIL**.
6. CRE group comparison: **FAIL**.
7. Lambda sensitivity: **FAIL**.
8. Severity monotonicity check: **FAIL**.
9. Ranking stability: **FAIL**.
10. Resume metrics automatically generated: **FAIL** — `outputs/reporting/resume_metrics.json` absent.
11. Simplified capital path is not misrepresented as Fed CET1: **UNKNOWN** — no Batch 4 implementation or result exists to evaluate.

## Batch 5 — Model Risk / External Validation / Delivery

Overall: `NOT_STARTED`.

1. Adaptive Conformal completed or explicit fallback: **FAIL** — neither implementation nor fallback decision exists.
2. Optional market validation completed or explicitly declined: **FAIL** — neither evidence nor decision record exists.
3. Final tables automatically generated: **FAIL**.
4. Final figures automatically generated: **FAIL**.
5. Ten-page report draft completed: **FAIL**.
6. README completed: **PARTIAL** — README documents Batch 1/2 and has an uncommitted Batch 3 section, but no final project/results/replication delivery.
7. Reproducibility audit passed: **FAIL** — no final audit exists.
8. Resume metrics automatically generated: **FAIL**.
9. All project limitations and failed results recorded: **PARTIAL** — Batch 1/2 limitations and the Batch 3 Bayesian fallback are recorded, but the project is incomplete.

## Reuse and migration classification

### KEEP

- Commits `8697871`, `8885bbc`, `0104915`, and `3d6e281`, including all Batch 1/2 code, tests, metadata, manifests, model specifications, EDA, and small model-result artifacts.
- Local ignored raw/standard/derived data; manifests verify current local inputs and no raw data should be uploaded.
- Batch 1 core sample, mappings, standardized/panel builders, flow logic, lineage/exclusion metadata, QA generator, and existing QA evidence.
- Batch 2 macro acquisition/availability policy, FDIC GFC noncurrent-loan input, model panel, AR/FE/SPJ/CRE interaction code, tests, and outputs.
- Uncommitted Batch 3 quantile/Bayesian/pseudo-stress code and tests as the starting point for scoped repair.
- Byte-identical Proposal and Batch-file relocation into `proposal/` and `workflow/`.
- Current Router workflow documents (`workflow/reusable_router_prompt.md`, `workflow/reusable_stage_worker_prompt.md`, config, and state); these are current migration inputs, not failed research code.

### FIX

- Close Batch 1's human source-document manual audit and document a defensible reconciliation rule/explanation for mapped segment NCO versus reported total NCO. Do not rebuild correct Batch 1 modules.
- Regenerate/validate Batch 3 on the amended 2005-start windows; produce pseudo-stress outputs and six figures; retain the explicit Bayesian fallback unless a valid posterior run is performed; then commit Batch 3.
- Harden `.gitignore` before first push to cover all prohibited data/secret/archive patterns.
- Correct `workflow/project_config.yaml`: repository path currently points to the `workflow` subdirectory, Proposal path is wrong, and stage file names/casing do not match actual files.
- Normalize and commit the Proposal/Batch-file relocation only after confirming the intended repository layout.

### ARCHIVE (list only; nothing deleted)

- Detached legacy Codex worktree `C:\Users\Carrey Chen\.codex\worktrees\1fe2\MF772` at `8885bbc`; no active task is using it. Archive/remove only through an explicit later cleanup decision.
- Prior inactive Batch 2/Batch 3 task records are historical orchestration records, not implementation evidence.
- No repository file was proven to be solely a failed old scheduler experiment. Therefore no in-repository content is designated for deletion or automatic archival in this audit.

## Router handoff

- Resume Batch 1 at the first unmet acceptance item only; reuse all passing work.
- Do not launch a Worker until the user starts the Router workflow.
- After Batch 1 acceptance closure, recognize and re-verify the existing Batch 2 implementation rather than rebuilding it.
- Migration mode: `MIGRATION_MODE_A`.

