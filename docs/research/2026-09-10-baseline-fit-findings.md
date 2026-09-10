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

## Decision order

1. Add and inspect the NFL closing spread/total RMSE benchmark from the same nflverse rows.
2. Split CFB holdout margin performance for games decided by under 14 points.
3. Add opponent-strength controls only if the close-game result supports that work.
4. Freeze only a lane that survives its relevant diagnostics and full calibration/provenance requirements.

The baseline report remains research-only until those checks are complete.
