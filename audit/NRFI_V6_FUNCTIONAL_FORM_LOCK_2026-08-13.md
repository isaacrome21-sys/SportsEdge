# NRFI/YRFI V6 Functional-Form Lock

This lock is committed before any 2026-08-13 forward-shadow outcome is used.

## Base artifact

V6 preserves the exact Statcast-aware `NRFI_V5_STATCAST` base scorer:

- SHA-256: `a12881071bb53a52c6dcfaaacbf6e7c844e329beb7bb2df204124c064d4b21cc`
- contact-transformer SHA-256: `bf61487279ac9a506318e9dfa078a866450dd4e363b1d06356e58852954133b2`
- V5 inherited feature contract must still literally contain all required NRFI Statcast features.

The V5 artifact remains failed/ineligible. It is used only as the frozen base probability generator for this new V6 development candidate.

## Observed development defect

The already-observed 2025 V5 evaluation is development evidence for V6:

- n = 1,870
- mean V5 YRFI probability = `0.4666385824133054`
- observed YRFI rate = `0.49625668449197863`
- V5 calibration z = `2.5616523851699866`

No 2026-08-13-or-later outcome enters this functional-form choice.

## Frozen repair

V6 uses a slope-1 logit intercept calibration only:

`logit(P_v6_YRFI) = logit(P_v5_YRFI) + 0.11867068977686865`

where the intercept is exactly:

`logit(0.49625668449197863) - logit(0.4666385824133054)`.

No slope, bucket, spline, tree, or additional parameter is fit in this V6 candidate. NRFI probability is exactly `1 - P_v6_YRFI`.

The transform is clipped only to `[0.001, 0.999]` after calibration.

## Why this form

This is a deliberately narrow repair to the aggregate calibration error that failed V5. It preserves ordering/ranking and the complete underlying Statcast feature consumption while changing only the global log-odds level. It cannot masquerade as a new predictive feature model.

## Frozen-status rule

Once the V6 candidate artifact is emitted and hashed, this offset may not be changed based on forward-shadow results. If it fails the predeclared V6 forward-shadow gates, a new version/protocol is required.
