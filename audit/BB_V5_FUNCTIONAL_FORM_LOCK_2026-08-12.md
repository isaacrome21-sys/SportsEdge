# BB-v5 Functional-Form Lock (Supplemental, pre-fit)

Recorded UTC: 2026-08-12T10:26:59Z

This file supplements, but does not modify, `audit/BB_V5_PREDECLARED_PROTOCOL_2026-08-12.md`. It exists because the original protocol locked the permitted candidate family but did not spell out the exact monotone calibration functional form. No BB-v5 fit has been executed before this record.

## Fixed functional form

For the 1.5-walk threshold only:

1. Compute the unchanged BB-v4 globally calibrated probability `p_v4`.
2. Assign the row to exactly one predeclared `pit_bb_hist` band: `<0.06`, `[0.06,0.08)`, `[0.08,0.10)`, `[0.10,0.12)`, `>=0.12`.
3. Within each band fit a one-dimensional logistic calibration model on `logit(p_v4)` only: `sigmoid(intercept_band + slope_band * logit(p_v4))`.
4. A fitted band is invalid if `slope_band <= 0`; do not coerce or clip the slope to make it monotone.
5. Output probability is clipped only to `[0.001, 0.999]` as the governing protocol permits.
6. No cross-band pooling, manual offsets, additional interactions, or fallback tuning are permitted.

## Date-blocked cross-fitting

2025 rows are split deterministically by calendar month of the pregame `officialDate`. For each held-out month, each band's calibrator is fit on all other eligible 2025 months and scored only on that held-out month. A band/fold with insufficient class variation to fit logistic regression is a hard candidate failure, not a reason to alter the form.

The final frozen BB-v5 band calibrators may be fit on all eligible 2025 rows only after the cross-fit gate passes.

## Evidence semantics

2026 through Aug. 10 remains `POST_HOC_CONFIRMATORY_NOT_PRISTINE_HOLDOUT`. The forward-shadow gate in the governing protocol remains mandatory for deployment.
