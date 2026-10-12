# Savant feature validation — 2026-10-11

Generated 2026-10-12T00:59:08.509626+00:00. Research only.

Train (features): 2026-09-01..2026-09-15. Test (priced): 2026-09-16..2026-09-30.
All Savant inputs strictly prior to each test game (no lookahead).
Market baseline: MISSING (no odds data) — comparisons are model-vs-model.

## A. xK% vs raw K% (pitcher strikeout propensity)

- Test starts: 1078
- Mean Poisson log-loss: xK% 1.68901 vs raw K% 1.6947
- Delta (xK − raw): -0.00569 (negative favors xK%)
- Verdict: **XK_WINS**

## B. Savant-augmented vs box-score-only (ML + TOTAL 8.5)

- boxscore_only/ML: n=167 brier=0.24343 log_loss=0.68
- boxscore_only/TOTAL_8.5: n=167 brier=0.25507 log_loss=0.70402
- savant_augmented/ML: n=167 brier=0.24191 log_loss=0.67987
- savant_augmented/TOTAL_8.5: n=167 brier=0.31396 log_loss=0.86046

- ML: brier Δ -0.00152, log-loss Δ -0.00013 → **SAVANT_WINS**
- TOTAL_8.5: brier Δ 0.05889, log-loss Δ 0.15644 → **BOX_WINS**

## C. HR prop model vs naive batter-HR-rate baseline

- Batter-games: 1772
- Model: brier 0.0907, log-loss 0.32884, mean P(HR) 0.1248, base rate 0.0993
- Naive: brier 0.09045, log-loss 0.32324
- Δ brier 0.00026, Δ log-loss 0.00561 → **BASELINE_WINS**

## Caveats
- Declared constants (not fit): HFA 0.12 runs, win-prob σ 4.0, total σ 4.5,
  38 PA/game, 22 BF/start, wOBA→runs scale 1.21. Paired comparison, so
  the delta isolates the Savant signal.
- Probable-pitcher fallback: actual most-pitches arm when the schedule
  payload lacks probablePitcher (post-game identity; quality signal
  itself is train-window only).
- Books-shade-overs observation used NOWHERE (evaluation-side only).

Standing bar: nothing ships as production-ready unless it wins
out-of-sample on BOTH Brier and log-loss.
