# Starter v2 vs defense blend — August 2026 one-shot

**This window is now spent.** Do not re-score August after changing constants.

- Window: **2026-08-01 → 2026-08-31**, 417 regular-season finals, 0 skipped
- Scoring: shipped Stage-1 Gamma-Poisson, 20k paths
- Identity: historical schedule `probablePitcher` stand-in (`ACTUAL_STARTER_STAND_IN_NO_PREGAME_PIT_ARCHIVE`); PIT unverified
- League rates: June–July starter innings only (23,189 outs; K 0.314 / BB 0.112 / HR 0.049 per out)
- FIP per-out weights: **HR 39, BB 9, K 6** (unit correction before this run)
- `league_ra9_proxy = 4.50` assumed, not measured
- `constants_sha256 = c349df6bbb38c8507440e86421649100ae88a636adc683d975fe6853dbd0158c`

Both starters `AVAILABLE` on 375 / 417 games. Remaining games used the neutral shell on the thin-history side.

## Gate (locked metrics)

| Model | Mean \|gap\| (pp) | Mean Brier |
|---|---:|---:|
| defense_blend | 1.51 | 0.2373 |
| starter_v2 | **1.17** | **0.2356** |

Both required comparisons improve. **Gate: PASS (provisional).**

## Game-total lines

| Line | Blend pred | V2 pred | Observed | Blend \|gap\| | V2 \|gap\| | Blend Brier | V2 Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6.5 | 0.669 | 0.666 | 0.659 | 0.98 | 0.66 | 0.2233 | 0.2225 |
| 7.5 | 0.556 | 0.553 | 0.547 | 0.96 | 0.61 | 0.2459 | 0.2441 |
| 8.5 | 0.491 | 0.488 | 0.470 | 2.11 | 1.76 | 0.2464 | 0.2450 |
| 9.5 | 0.392 | 0.388 | 0.372 | 2.00 | 1.65 | 0.2338 | 0.2308 |

## Continuous totals (descriptive)

| Model | MAE | RMSE | Mean error |
|---|---:|---:|---:|
| defense_blend | 3.50 | 4.40 | +0.05 |
| starter_v2 | 3.48 | 4.36 | +0.01 |

## Authority

Pass is **provisional**. Production adoption still needs either PIT-bound confirmation from the running archive outside barred windows (playoffs / next season) or explicit ops acceptance of the stand-in identity. Weather remains unused.
