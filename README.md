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
bank-quarter flag.  The capital field is labeled a proxy pending the Batch 2
capital-model interface.  No estimated results or filled-zero loss observations
are used.
