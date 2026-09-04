# MF772 bank credit-stress panel

Batch 1 builds a reproducible `bank × loan segment × quarter` panel from FFIEC
Call Report bulk archives for 2005Q1–2025Q4.  The implementation does not ship
raw Call Report data: `data/raw/` is ignored and every archive is recorded in
`data/manifests/ffiec_manifest.csv` with its official URL, timestamp, SHA-256,
report date, and version.

## Run

```powershell
python -m pip install -r requirements.txt
python scripts/run_batch1.py --pilot
python scripts/run_batch1.py --full
python -m pytest -q
```

## Batch 2

Batch 2 consumes the ignored, real `data/derived/credit_panel.parquet` produced
by Batch 1.  If a checkout contains the committed manifest but not its ignored
archives, restore the archives without changing the original manifest, then run
the existing Batch 1 pipeline followed by Batch 2:

```powershell
python scripts/recover_batch1_inputs.py
python scripts/run_batch1.py --full
python scripts/run_batch2.py
```

The recovery command writes `data/manifests/ffiec_recovery_manifest.csv`, which
records each fresh source download timestamp and SHA-256.  Batch 2 writes its
macro availability audit to `metadata/macro_release_calendar.csv`; its explicit
ALFRED/final-vintage fallback limitation is written to
`metadata/macro_vintage_limitation.md`.

## Batch 3

Batch 3 consumes the ignored real `data/derived/model_panel.parquet` generated
by the preceding batches.  It fits segment-specific 0.50/0.75/0.90 quantile
models with bank effects, a Student-t partial-pooling Bayesian model, frozen
expanding-window OOS comparisons, and recursive historical pseudo-stress
windows.  Install the declared Bayesian extra and run:

```powershell
python -m pip install -r requirements.txt
python scripts/run_batch3.py
```

The output in `outputs/validation/` records all OOS and tail metrics.  The
historical pseudo-stress forecasts use observed historical macro paths, recurse
only through lagged NCO, and freeze future bank controls at their final
pre-window values to prevent future-control leakage.

`--pilot` obtains 2005Q1, 2009Q4, 2020Q2, and 2025Q4.  `--full` obtains the
complete 2005Q1–2025Q4 sequence, reuses manifest-backed raw snapshots without
overwriting them, and regenerates the standard layer, panel, QA reports, and
metadata.  Paths and selection policy are in `configs/project.yaml`.

## Sources and limits

The raw source is FFIEC CDR Public Data Distribution; the FDIC BankFind public
API supplies the 2025Q4 candidate universe and merger/consolidation history.
Field definitions, effective dates, units, and source references live in
`metadata/field_mapping.csv`.  YTD flow values are quarterlyized explicitly;
missing predecessor quarters stay missing and downward revisions stay negative.

The lineage history is branch-granular, so its merger events are collapsed to a
bank-quarter flag. Schedule RC-R supplies the actual Tier 1 capital and Tier 1
risk-based ratio; Schedule RC book equity is retained separately as
`equity_capital`. No estimated results or filled-zero loss observations are used.
