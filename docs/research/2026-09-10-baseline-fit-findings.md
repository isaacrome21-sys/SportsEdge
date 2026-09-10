# Baseline fit findings — 2026-09-10

Status: empirical research record only. These results do not create a production model, Model_P artifact, Truth Gate pass, or OFFICIAL betting eligibility.

## First fitted outputs

The first hosted fit used free historical result sources and produced held-out outputs for MLB, NFL, and CFB.

Observed cross-validated ridge alphas:

- MLB margin: 300.0
- MLB total: 300.0
- NFL margin: 100.0
- NFL total: 100.0
- CFB margin: 300.0
- CFB total: 0.1

The assumed production alpha of 10.0 is therefore unsupported by this first empirical run. No production alpha should be frozen from these results alone.

## Placebo review

Shuffled-label holdout R2 values were:

- MLB: negative/slightly negative
- NFL margin: +0.0127
- NFL total: +0.0036
- CFB margin: +0.0009
- CFB total: -0.0009

The small positive football placebo values are not by themselves proof of leakage, but they require review. The CFB margin result is especially sensitive to talent-gap effects because the baseline uses rolling points for/against and has no opponent-strength control.

## Requested diagnostics

### NFL closing-market benchmark

The corrected report uses raw nflverse spread_line values. Across 272 holdout games:

- Margin model RMSE: 13.2120
- Closing spread RMSE: 12.3595
- Spread-line correlation with actual home margin: +0.4921
- Total model RMSE: 13.3600
- Closing total RMSE: 13.1325

The positive correlation confirms the raw spread_line orientation. The model loses to the closing spread by about 0.853 RMSE and loses to the closing total by about 0.228 RMSE. NFL does not pass the first market-relative screen.

### CFB close-game split

For 415 CFB holdout games decided by under 14 points:

- Full margin model R2: 0.3587
- Under-14 margin model R2: -0.6249
- Under-14 model RMSE: 10.2777
- Under-14 mean-baseline RMSE: 8.0628

The strong full-sample CFB margin result does not survive the close-game filter. This supports the talent-gap/blowout explanation and disqualifies this baseline from betting-model certification.

## Decision

- Keep all three fitted outputs research-only.
- Do not freeze alpha 10.0 or any replacement alpha yet.
- Do not certify NFL margin or total; both lose to the closing market in this baseline test.
- Do not certify CFB margin; it is worse than the mean on close games.
- Treat CFB total alpha 0.1 as a noise-sensitive CV result pending robustness checks.
- Treat MLB as research-only pending its own market-relative and calibration evidence.

The baseline report remains research-only until the full calibration, provenance, and Truth Gate requirements are complete.


## Post-holdout protocol

The 2025 NFL measurements are now validation results and must not be reused for feature selection. No feature iteration has been evaluated against a replacement holdout.

- Reserved future holdout: the completed 2026 NFL season, evaluated only after the feature set is frozen.
- Current feature-search attempts allowed: NOT LOCATED IN REPOSITORY; do not invent a value or silently substitute one.
- Required before feature work: resolve the existing Phase 3 multiple-testing policy and record its exact attempt budget.
- Required placebo control: compute a deterministic 200-shuffle null on training/CV data only, before evaluating any new feature set.
- NFL closing-market comparison remains the primary decision metric; mean-baseline improvement alone is insufficient.
