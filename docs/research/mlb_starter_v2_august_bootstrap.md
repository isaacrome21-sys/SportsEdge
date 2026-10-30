# August starter v2 — paired bootstrap (no re-specification)

Same 417-game August window. Constants unchanged. Games resampled with
replacement, 20,000 replicates, seed `20260831`. Unit of pairing is the game.
Per game, Brier is the mean of the four game-total lines (6.5 / 7.5 / 8.5 / 9.5).
Delta = starter_v2 − defense_blend (negative means v2 better).

## Brier

| | |
|---|---:|
| Observed blend | 0.237343 |
| Observed v2 | 0.235613 |
| Observed Δ | −0.001730 |
| 95% CI Δ | [−0.004618, +0.001181] |
| P\*(Δ ≥ 0) | 0.12 |
| Excludes 0? | **No** |

## Mean |gap| (descriptive; 5,000 replicates)

| | |
|---|---:|
| Observed Δ (pp) | −0.35 |
| 95% CI Δ (pp) | [−0.62, +0.46] |
| Excludes 0? | **No** |

## Reading

The pre-registered gate was "improves," and the point estimates do. The paired
bootstrap does **not** show the Brier improvement is distinguishable from zero.
That is "not worse, maybe slightly better," not a clear upgrade.

Promotion from here is a judgment call, not a statistical slam dunk. If promoted,
it remains provisional on starter identity (PIT archive from Sept 13 onward /
playoffs / next season).
