# MF772 Bank Credit Stress Testing

> **Repair-cycle status (limited R4, 2026-09-07): complete pending Router review.**
> Formal delivery artifacts use the repaired R1-R3 chain and the manifest-hash-verified
> Federal Reserve 2026 scenario inputs. Legacy stress, interval, report, and resume
> outputs are audit-only unless they carry the current R4 metadata.

## Problem

MF772 is a reproducible public-data framework for segment-level credit analysis of
U.S. regional banks. It reconstructs quarterly net charge-off (NCO) rates and
translates the Federal Reserve 2026 baseline and severely adverse macro paths into
static-exposure conditional-mean credit-loss estimates. It is not a bank-failure
classifier, a causal CRE study, a confidential FR Y-14 model, or a CET1 forecast.

## Data

The repaired historical panel contains 33 banks, three segments (CRE, C&I, and
closed-end Mortgage), 84 quarters, and 8,145 rows. It retains 60 explicit
unavailable segment rows for a POR-verified FFIEC 051 interval and does not impute
their financial values. Effective-dated mappings and source/reconciliation caveats
are documented under `metadata/`.

The common 2025Q4 R4 stress universe contains 31 banks with complete eligible C&I
and CRE jump-off states. Mortgage is historical-panel evidence only: no Mortgage
stress loss is reported because no approved Mortgage stress model exists.

## Method

Formal R4 paths cover 2026Q1-2028Q1 and include only registry-authorized pairs:

- AR mean for C&I and CRE as the formal comparison baseline.
- Dynamic FE for C&I as a limited challenger/sensitivity. R2 found lower
  equal-observation RMSE in only 1 of 8 segment-window comparisons.

Dynamic FE CRE, every quantile model, and Bayesian outputs are excluded from formal
stress paths and rankings. Quantiles retain one-step diagnostic use only; there is
no cumulative-loss quantile or multi-period tail-distribution result.

Quarterly modeled loss is calculated as:

```text
quarter_loss_thousands
  = annualized_nco_rate_decimal / 4 * exposure_thousands
```

The reported ratio is cumulative modeled credit loss divided by starting Tier1.
It is a credit-loss burden measure, not capital depletion, CET1 change, or a full
capital roll-forward.

## Key Results

- The AR C&I-plus-CRE aggregate is 7,299,383 thousand under both official paths.
  AR contains no macro scenario variables, so scenario invariance is expected and
  is a baseline-model limitation—not evidence that baseline and severe are equally
  stressful.
- Dynamic FE C&I is published only as a limited challenger. Its severely adverse
  conditional-mean aggregate is 12,286,840 thousand; it is not a full-portfolio
  result and not evidence of model superiority.
- Higher CRE-to-Tier1 mechanically produces higher loss-to-Tier1 under the
  equal-loss-rate exposure decomposition. The repaired R2 interaction does not
  support an additional per-dollar CRE amplification effect; its 95% interval
  includes zero.
- Baseline/severe conditional-mean paths are publishable with these scope labels.
  Capital depletion, Mortgage stress, cumulative tail loss, Bayesian stress, and
  market external validation are unavailable or not evaluated.

## Reproducibility

Install dependencies and run the bounded downstream chain:

```powershell
python -m pip install -r requirements.txt
make stress
make report
python -m pytest -q --basetemp .pytest-local
```

`make stress` re-fetches the three retained Federal Reserve files and requires
their bytes to match `metadata/fed_2026_scenario_manifest.csv`. The formal entry
then validates R1/R2/R3 mapping, manifest, model-panel, specification, registry,
and artifact hashes. `make report` creates only the supported T1-T5 tables,
figures, errata, resume metrics, and ten-page report.

The reproducibility audit distinguishes unit, integration, artifact-consistency,
and limited R4-chain evidence. It does not claim that R1-R3 were rerun during the
R4 invocation.

## Limitations

- Two bounded FFIEC gross-flow rows remain `REVIEW_REQUIRED` and explicitly listed.
- Some historical macro inputs use documented final-vintage fallbacks.
- AR cannot distinguish the official scenarios because it has no macro predictors.
- Dynamic FE C&I is weak as an incremental mean challenger; Dynamic FE CRE is
  diagnostic-only because a required path feature is unavailable.
- Quantile crossing occurred in 507 one-step diagnostic rows before rearrangement.
  Multi-period tail distributions and residual-calibration expansion were not
  evaluated.
- No full capital roll-forward, Mortgage stress model, Bayesian result, market
  validation, machine-learning challenger, or new sample expansion is included.

See `outputs/reporting/errata.md` and
`outputs/reporting/reproducibility_audit.md` for the formal delivery boundaries.
