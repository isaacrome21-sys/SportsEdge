# Result: CBB as-of team ratings walk-forward (2024-25)

Pre-registration: `CBB_ASOF_RATINGS_PREREG_20261013.md` (`98695a6`, committed before the code was run). **Governance flag:** that prereg path needs ChatGPT registration. Code: `sportsedge/sports/cbb/asof_ratings.py`, `asof_harness.py`, `scripts/run_cbb_asof_harness.py`. Cache: `/workspace/cbb_cache` (outside the repo), 6,169 completed games from free ESPN D1 scoreboards and box scores; 6,162 loaded, 14 skipped. Lines are **NAIVE_STANDIN**, not market lines. Market baseline MISSING.

**Illinois exclusion:** 378 games with an Illinois school (by ESPN id) were excluded from evaluation and output (BLOCKED ILLINOIS_COLLEGE_EXCLUDED). They were used only as training opponents.

| Market | n | Brier model | Brier naive | LL model | LL naive |
|---|---|---|---|---|---|
| Moneyline | 4477 | **0.2293** | 0.2468 | **0.6635** | 0.6924 |
| Spread (stand-in) | 4477 | 0.2517 | **0.2500** | 0.6972 | **0.6932** |
| Total (stand-in) | 4474 | **0.2450** | 0.2500 | **0.6831** | 0.6932 |

## Decision (fixed rule: all three Brier plus moneyline log-loss): **FAIL** (spread loses)

## Diagnosis (no re-fit; any fix needs a new pre-registration)
- **Home court is badly biased.** The fixed spec estimates home court as the raw mean home margin in non-neutral games. That came out ≈ **10.2 points** (as of 2025-02-15), against a typical ~3. Early-season home schedules are dominated by mismatches (strong hosts versus weak and non-D1 visitors), so raw home margin confounds strength with venue.
- **The inflated home court flows into everything.** It sits in both the ratings (efficiency is de-biased by H/2) and the predictions, pushing home margins too high. That is the likely cause of the spread loss and the weak moneyline (0.229).
- **Team ordering itself looks sensible.** Top of the table as of Feb 15: Auburn, Duke, Houston, Florida. Margin correlation on Feb 15–28 games is 0.56.
- **Proposed v2 (to pre-register):** estimate home court jointly as a parameter in the opponent-adjusted fit (the residual after team strengths), and restrict training to D1-vs-D1 games or shrink non-D1 opponents to a low prior.
