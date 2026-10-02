# Held-out results: starter vs defense blend (2026-09-15 → 2026-09-27)

**Diagnostic only.** Starter identity not PIT-archived; weather held neutral.

- Window: 174 regular-season finals (same span as dispersion validation)
- Scoring: shipped Stage-1 Gamma-Poisson (`r = 5.217229403204152`), 20k paths
- Candidate: existing `context_adjusted_means` starter multiplier on defense blend

## Game-total lines (6.5 / 7.5 / 8.5 / 9.5)

| Model | Mean \|gap\| (pp) | Mean Brier |
|---|---:|---:|
| defense_blend | **1.38** | **0.2364** |
| starter_adjusted | 2.62 | 0.2418 |
| offense_only | 1.36 | 0.2399 |

Starter is **worse** on both gate metrics. Do not promote.

## Continuous totals

| Model | MAE | RMSE | Mean error |
|---|---:|---:|---:|
| defense_blend | 3.12 | 4.09 | +0.47 |
| starter_adjusted | 3.20 | 4.13 | +0.11 |

Starter shrinks mean bias slightly but hurts absolute error and line calibration.

## Gate decision
**FAIL.** Keep production on defense blend until a new starter specification beats this window (or a pre-registered successor window) on mean \|gap\| **and** Brier under the shipped dispersion.
