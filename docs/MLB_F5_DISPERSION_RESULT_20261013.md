# Result: F5-specific dispersion / zero-inflation (pre-registered)

Pre-registration: `MLB_F5_DISPERSION_PREREG_20261013.md`, committed at `9481a00` before fitting. Script: `scripts/run_mlb_f5_dispersion_holdout.py`. The market baseline is MISSING.

## Fit (2024 PIT rows only, n = 4,538 team-games)
r_f5 = **2.5**, π = **0.06** (grid MLE; log-likelihood −9306.85).

## 2025 holdout (n = 4,552 team-games per line)

| Line | Brier: cand / naive / base NB | Log-loss: cand / naive / base NB | mean p / hit |
|---|---|---|---|
| 0.5 | **0.16752** / 0.16765 / 0.17065 | **0.51764** / 0.51799 / 0.52894 | 0.788 / 0.787 |
| 1.5 | 0.24509 / **0.24433** / 0.24736 | 0.68341 / **0.68176** / 0.68837 | 0.592 / 0.576 |
| 2.5 | 0.24126 / 0.24124 / 0.24165 | 0.67554 / 0.67554 / 0.67633 | 0.415 / 0.406 |

## Decision: **FAIL** (fixed rule: beat naive on both metrics at all three lines)
- **Gains:** the candidate fixes most of the baseline's miscalibration, beats the baseline NB at every line, and beats naive at 0.5.
- **Losses:** it still loses to naive at 1.5, where it overstates OVER by about 1.6 points, and it only ties at 2.5.
- **Conclusion:** team mean information adds no measurable skill over the league frequency for F5 team totals.
- **Next steps:** no promotion, no eligibility change, and no re-fit on 2025. Any variant (for example starter-quality inputs) needs a new pre-registration.
