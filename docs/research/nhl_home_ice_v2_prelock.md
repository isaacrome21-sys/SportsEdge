# NHL rate v2 pre-lock (home ice + regulation-only)

Written 2026-09-29. Do not score the new window yet.

## Review of #1249 / #1253

| Market | Pred | Obs | Gap | Ship now |
|---|---:|---:|---:|---|
| Home win | 56.4% | 52.2% | 4.27 pp | **NO_MODEL** |
| Over 5.5 | 56.1% | 57.5% | 1.31 pp | price **as validated** |
| Over 6.5 | 45.3% | 46.9% | 1.67 pp | price **as validated** |
| PL −1.5 | 32.6% | 30.1% | 2.44 pp | lean only |

1,302 scored games. 4.27 pp on home win is ~3× binomial noise.

## Ship the double-count totals, do not quiet-fix

The 1.3–1.7 pp totals result is from the version that **fits on final scores and then adds OT/SO again**. That is the validated owner. Shipping totals means shipping that exact path. Do not remove the double-count and keep calling #1249 the totals validation.

2025-26 REG official `/v1/score` (n=1,312):

- REG 986 / OT 207 (15.8%) / SO 119 (9.1%)
- Mean **final** goals 6.25 vs **regulation** ~6.01

## Brier vs naive (constant-p bound)

If the model were a constant 56.4% home: Brier 0.251 vs coin 0.250 vs 2024-25 home rate 0.251. No ML skill.

## v2 window (unused — locked before any 2026-27 game)

The regulation-only fit changes **every** λ, so it moves moneyline, puck line, and totals together.

- **Fit:** 2024-25 REG, **regulation goals only** (drop OT goals and the SO dummy). Home-ice free. Same sim as production after the fit (no second OT/SO add on a final-score mean).
- **Validate once:** 2026-27 REG `2026-10-08` through `2026-11-30` (~350–400 games). Oct 8–31 alone is only ~180–200 games (±3.5 pp noise), too close to the 4-point home bias to decide.
- **October snapshot:** numbers through Oct 31 may be posted as a first read. They do not pass, fail, or retune. The one-shot verdict is November 30.
- **Score all three, one look, on the full window:**
  - moneyline home-win |gap| and Brier vs coin and vs 2024-25 home-win rate
  - puck line −1.5 |gap|
  - totals 5.5 and 6.5 |gap| and Brier
- **Pass:** ML |gap| ≤ 2.0 pp **and** ML Brier beats both naives **and** neither totals line gets worse than the shipped #1249 gaps by more than 1.0 pp.
- Fail → new window. No second look at Oct–Nov 2026. Shipped totals stay on the double-count owner until a pass.

2025-26 is spent.
