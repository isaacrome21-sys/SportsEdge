# NHL home-ice v2 + OT/SO audit (pre-lock)

Written 2026-09-29. Do not score the new window yet.

## Review of #1249 / #1253

| Market | Pred | Obs | Gap | Call |
|---|---:|---:|---:|---|
| Home win | 56.4% | 52.2% | 4.27 pp | **NO_MODEL** until refit |
| Over 5.5 | 56.1% | 57.5% | 1.31 pp | price |
| Over 6.5 | 45.3% | 46.9% | 1.67 pp | price |
| PL −1.5 | 32.6% | 30.1% | 2.44 pp | lean only |

1,302 scored games. 4.27 pp on home win is ~3× binomial noise. Real bias, not the gate.

## OT / SO double count (confirmed)

2025-26 REG official `/v1/score` (n=1,312):

- REG 986 / OT 207 (15.8%) / SO 119 (9.1%)
- Mean **final** goals 6.25
- Mean **regulation** goals ~6.01
- SO dummy goals in the final score: 119

`gameOutcome.lastPeriodType` is REG / OT / SO. The `goals[]` list tags periodType. Final `homeTeam.score` includes the shootout winner goal.

Rate v1 was fit on those **final** scores, then the card sim treats the fitted λ as regulation and **adds OT/SO again** when tied. Extra ~0.25 goals are in the mean twice. Totals still landed inside 2 pp; moneyline did not.

Next fit uses regulation goals only (drop OT goals and the SO dummy).

## Brier vs naive (constant-p bound from the published rates)

Per-game vectors were not re-run this pass. If the model were a constant 56.4% home:

- model 0.251
- coin 0.250
- 2024-25 home rate 55.9% → 0.251

So “within 5 points” did not show skill on moneyline. Promotion of ML is blocked.

## Home-ice v2 window (unused — write now, score once)

- **Fit:** 2024-25 REG, regulation goals only, home-ice term free.
- **Validate once:** 2026-27 REG `2026-10-08` through `2026-10-31` (opening weeks). 2025-26 is spent.
- **Pass:** home-win |gap| ≤ 2.0 pp and Brier better than both a coin and the 2024-25 home-win rate, on that window only.
- Fail → new window, no second look at Oct 2026.

#1253 may price totals. Puck line stays a lean. Moneyline stays `NO_MODEL:HOME_ICE_UNVALIDATED` until v2 passes.
