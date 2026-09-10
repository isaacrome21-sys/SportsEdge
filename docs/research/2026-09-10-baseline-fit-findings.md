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

Using the same nflverse source, on 272 holdout games:

- Margin model RMSE: 13.2120
- Closing spread RMSE: 18.3098
- Total model RMSE: 13.3600
- Closing total RMSE: 13.1325

The total baseline is worse than the closing total by about 0.228 points RMSE. The margin comparison is reported under the conventional home-margin interpretation of nflverse spread_line and still requires source-convention review before any certification decision.

### CFB close-game split

For 415 CFB holdout games decided by under 14 points:

- Full margin model R2: 0.3587
- Under-14 margin model R2: -0.6249
- Under-14 model RMSE: 10.2777
- Under-14 mean-baseline RMSE: 8.0628

The strong full-sample CFB margin result does not survive the close-game filter. This supports the talent-gap/blowout explanation and makes CFB margin unsuitable for certification without opponent-strength and market-relative testing.

## Decision order

1. Keep all three fitted outputs research-only.
2. Do not freeze alpha 10.0 or any replacement alpha yet.
3. Verify the nflverse spread sign convention and add a same-sample market comparison to the production evidence format.
4. Treat NFL total as failing the first market-relative screen.
5. Treat CFB margin as failing the close-game diagnostic until redesigned.
6. Treat CFB total alpha 0.1 as a noise-sensitive CV result pending robustness checks.
7. Consider only a lane that survives relevant market-relative diagnostics and full calibration/provenance requirements.

The baseline report remains research-only until those checks are complete.
