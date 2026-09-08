# Reproducing the evidence

## 1. Inspect and verify a clean checkout

Use Python 3.11+ in an isolated environment. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python scripts/export_results.py --verify
python scripts/plot_results.py
python -m pytest -q -p no:cacheprovider
```

These commands need no bulk data. Verification checks each selected evidence file
against its SHA-256, checks the field mapping, and recomputes the published summary.
The figure is generated from the same evidence. This is **snapshot verification**,
not a claim that downloading and refitting the full research chain has been rerun.

`.gitattributes` disables newline conversion for CSVs and other hash-bound inputs
so their source bytes survive checkout on Windows, macOS, and Linux.

The original analytical checkpoint is Git commit
`ca6c88b` (preceding the portfolio reorganization). Individual source commits,
run IDs, artifact hashes, and input hashes are preserved in
[results/provenance.json](../results/provenance.json). Evidence CSVs are copied
byte-for-byte. Historical run/version labels inside those files identify their
lineage and have not been cosmetically rewritten.

Tests of formulas, timing, common scoring keys, recursive controls, and model-use
restrictions run without a historical dataset. Eight integration checks need
the removed full analytical outputs and skip when those inputs are absent.
The full suite was also run against the original local artifacts before cleanup.

Verification of the reorganized repository on 2026-09-08:

- Compact checkout: **101 passed, 8 skipped** (local-artifact integration checks).
- With the archived analytical inputs temporarily restored: **109 passed**.
- All 10 evidence-file hashes and all summary calculations verified.
- The README figure was regenerated and visually inspected.

The statistical estimators and published numerical evidence were not changed by
the file reorganization. Model refitting and external-data downloading were not
part of these verification runs.

## 2. Recalculate the main findings

- **Data scale:** `results/evidence/sample.csv`; unique `raw_code` values in
  `metadata/field_mapping.csv` supply the 73-code inventory.
- **5.38% tail improvement:** filter `tail_metrics.csv` to `window == 0`
  (pooled OOS), `segment == CRE`, `tau == 0.9`, and
  `prediction_version == POST_REARRANGEMENT`. Compute
  `100 * (1 - dynamic_quantile.pinball_loss / ar_quantile.pinball_loss)`.
  Both rows have 1,264 scored observations. C&I has 1,525 and a 2.58% reduction.
  Window 0 is pooled evidence, not an additional test window. The raw
  pre-rearrangement CRE result is approximately 4.75%; version choice matters.
- **Mean model comparison:** pair AR and dynamic FE RMSE by segment and window
  in `mean_model_comparison.csv`; the dynamic model wins 1 of 8 comparisons.
- **Stress:** filter `stress_by_bank.csv` to CI and the two official scenarios;
  sum `cumulative_loss_thousands` separately by model and scenario, then divide
  by 1,000,000. Do not aggregate the AR benchmark and FE challenger together.
- **Bayesian status:** `bayesian_diagnostics.csv` records explicit sampling
  skips; `validation.json` records Bayesian validation as `NOT_EVALUATED`.

The publication script checks saved evidence, not the original observation-level
forecasts. During the reorganization, the Q90 scores and common scoring keys were
also recomputed directly from those original forecasts. Large prediction files
are local analytical artifacts and are not part of the public snapshot.

## 3. Data collection and analytical entry points

| Script | Role | Required inputs / scope |
| --- | --- | --- |
| `download_call_reports.py` | Recover quarterly FFIEC archives with bounded network requests and a separate recovery manifest | Network access; project date range |
| `collect_data.py --pilot` / `--full` | Download, select sample, standardize, construct panel, write QA | Network access; may refresh sample metadata and manifests; run in a separate research checkout |
| `audit_sources.py` | Trace selected panel observations to archive source values | Raw archives, standard layer, credit panel |
| `rebuild_panel.py` | Replay the source-verified panel and transition audit | Exact historical archives, source audit, and pre-correction comparison panel |
| `fit_mean_models.py` | Build macro/model panel and fit AR, FE, and CRE interaction | Validated credit panel and external data |
| `rebuild_models.py` | Replay corrected information-set and model-comparison gates | Approved panel run/hash, transition audit, historical Git state |
| `validate_models.py` | One-step quantiles and historical recursive diagnostics | Approved model-panel run and source lineage |
| `evaluate_bayesian.py` | Optional broader estimator experiment | Model panel and Bayesian dependencies; not a way to reproduce the headline tail result |
| `run_stress.py` | Registry-gated conditional-mean stress replay | Approved panel, model-use registry, upstream lineage, manifest-matching Fed inputs |
| `build_report.py` | Detailed analytical report generation | Validated stress output chain |
| `export_results.py` | Export selected existing evidence, or verify it with `--verify` | Recorded outputs for export; committed evidence for verification |
| `plot_results.py` | Regenerate the README figure | Committed evidence only |

The historical replay scripts deliberately retain exact run/hash checks. They
are not a turnkey download-to-stress pipeline on a fresh checkout: some require
pre-correction comparison artifacts and upstream validation sidecars. Removing
those gates would falsely equate a new run with the validated historical result.
The core reusable transformations and estimators are in `src/bankstress/`.

For an exact historical replay, use a separate checkout of `ca6c88b`, restore its
manifest-matching raw and validated local inputs, and follow its recorded run
contracts. Git history preserves the original orchestration documents; those
documents, caches, intermediate panels, old reports, and binary predictions are
excluded from the current portfolio tree. Public APIs may revise historical
files; a hash mismatch requires source review, not an automatic manifest update.

During cleanup, existing local workflow edits and analytical outputs were saved
outside the repository. That local archive is a recovery convenience, not a
dependency of the public evidence-verification commands.

For Bayesian experimentation, install `python -m pip install -e ".[test,bayesian]"`.
The configured seed is 772, with explicit priors and convergence thresholds.
No posterior result should be published unless sampling and convergence checks
actually complete. Fresh experiments must not overwrite the published snapshot
without an explicit evidence review.
