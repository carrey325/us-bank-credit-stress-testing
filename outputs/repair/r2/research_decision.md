# R2 research decision

## Gate result

R2's corrected time and evaluation contracts pass. The recommendation is **minimal R3**. This is a research-scope recommendation, not permission to start R3 before Router review and the required user decision.

## What the data repair changed

The approved R1 panel replaces the invalid historical model input, preserves unsupported 031/051 periods as missing, prevents gap bridging, and retains two bounded `REVIEW_REQUIRED` flow rows. `OLD_INVALID` metrics are not directly comparable to corrected-target metrics. `DATA_FIXED_SAME_SPEC_DIAGNOSTIC` isolates the R1 data change while retaining known time/evaluation defects.

## AR versus Dynamic FE

Dynamic FE has lower equal-observation RMSE than AR in 1 of 8 segment-window comparisons. All comparisons use identical bank/segment/origin/target keys. `r2_vs_test_mean` and `sse_improvement_vs_ar` are separately named; exposure-weighted results answer a dollar-exposure-weighted evaluation question and are not selected in place of equal-weight results.

## Problem windows and segments

The largest observation-level errors and their R1 audit statuses are in `error_contributors.csv`. For the 2025Q4 target, CI: 30/33 prediction-eligible and 29/33 evaluation-eligible; CRE: 0/33 prediction-eligible and 0/33 evaluation-eligible. CRE loses the 2025Q4 target solely because the final-vintage fallback has no origin-known 2025Q3 CRE-price-growth value; it is retained missing rather than filled or replaced. C&I retains 30 prediction candidates, while target absence independently removes one of them from evaluation. At the 2025Q4 origin for the forecast-only 2026Q1 target, prediction-eligible counts are CRE=0 and C&I=31; all remain unscored because targets are outside the R1 horizon. Actual FE unseen-entity attrition is recorded by window/segment: window 1 CI: 18 rows / 1 entities from 585 candidates; window 2 CI: 0 rows / 0 entities from 342 candidates; window 3 CI: 0 rows / 0 entities from 239 candidates; window 4 CI: 0 rows / 0 entities from 482 candidates; window 1 CRE: 195 rows / 16 entities from 479 candidates; window 2 CRE: 0 rows / 0 entities from 354 candidates; window 3 CRE: 0 rows / 0 entities from 246 candidates; window 4 CRE: 0 rows / 0 entities from 466 candidates. Every bank-level reason is enumerated in `sample_attrition.csv`; no target outcome was used to determine prediction eligibility.

## CRE hypothesis

The re-estimated primary interaction uses Exposure(t-1) × contemporaneous realized CRE YoY-growth(t), with `shock_period == target_period`. The realized shock is explicitly final-vintage ex-post information and is not used as forecast-origin information. Its estimate is -5.9863299e-06, bank-clustered SE 1.3113601e-05, and 95% CI [-3.1688988e-05, 1.9716329e-05]. The interval includes zero. With growth positive, a decline-magnitude coefficient has the opposite sign. This is not stable evidence of an additional unit-loss-rate amplification; it is not causal and does not replace the mechanical exposure effect. The time-varying exposure main effect is included. CRE-share and exact-2021Q4 forward exposure are the only limited robustness variants, with no significance search. The fixed-exposure audit finds 30 banks with a valid 2021Q4 exposure and excludes/marks 3 unavailable banks rather than substituting stale pre-gap values.

## Worth validating next

Only the already-scoped tail/historical checks needed to determine one-step and stress-path uses are justified. Bayesian work, automated model search, market validation, and new research families remain deferred. Because the mean-model gain is not broadly stable, the evidence supports a minimal R3 rather than expansion.
