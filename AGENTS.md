# US Bank Credit Stress Testing

This is a public research portfolio focused on data collection, empirical
credit-loss modeling, and stress-scenario interpretation.

- Read `README.md`, `docs/data.md`, and `docs/reproduction.md` before changing
  definitions or entry points. Inspect Git status and preserve user edits.
- Never invent data, estimates, improvements, or citations. Numerical claims
  must trace to `results/evidence/` and `results/provenance.json`.
- Preserve reporting scopes, missingness, source availability, and common
  out-of-sample scoring keys. Do not change methods to improve displayed results.
- Raw data are immutable local inputs. Exclude caches, intermediate datasets,
  generated reports, and model binaries from Git; publish compact evidence.
- Archived run IDs and gates in source identify historical analytical contracts.
  Do not bypass them to make fresh output appear validated.
- Distinguish implemented Bayesian methods from validated posterior evidence,
  one-step quantiles from cumulative stress distributions, and credit-loss burden
  from a capital roll-forward.
- Prefer RTK for supported verbose CLI commands; use `rtk proxy` for raw evidence
  after a failed or ambiguous compressed command before retrying unchanged.
- Test relevant behavior and verify published evidence before committing.
  Do not rewrite unrelated history or publish bulk data or credentials.
