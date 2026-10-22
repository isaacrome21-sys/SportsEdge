# NBA totals pair-mean V3 — single-challenger research preregistration

Locked before implementing or scoring V3 on the historical archive: 2026-10-21 CT.
Parent: DRAFT NBA totals scoring-level V2 #2462 at `a1da632cb1a6238692884332cfef378d74dbcb42`. This record is not a registry promotion, forward capture, betting authorization, or independent market admission.

## Hypothesis and fixed construction

The parent V2 sums the shrunk **offense and points-allowed deviation for both teams**. Because each team's own historical combined game total already carries both scoring and conceding effects, the sum may double-count each team's high-/low-total style. A matchup of two teams should use the *average* of their historical game-total effects instead of the sum. One predeclared V3 challenger; no parameter search on the evaluation cohort.

All raw inputs and eligibility are **identical to the existing V2 date-only screen**:
- Pinned public SBR archive `flancast90/sportsbookreview-scraper`, commit `1a820e50c6fbd0276cde073c22bfffae78930868`, path `data/nba_archive_10Y.json`, Git blob `f5ba0d4f8f729236fdd8883a65189f2d6443338c`.
- Each target uses at most 450 prior games whose **calendar date is strictly earlier** than the target date. Never use same-day results, future scores, a target result, or any sportsbook line as model input.
- Require >=30 prior league games and >=5 team games for **each** target team. Preserve exact V2 aliases, validity filters, season 2015–2021 cohort and available market-reference pairing. No deletions based on size or sign of an error.
- Prior league scoring per team `L = mean((home_points+away_points)/2)`.
- For each team `t`, let `S_t` be its mean scored points and `C_t` its mean conceded points in those same prior fixtures; `n_t` is its prior count, and `w_t = n_t/(n_t+20)`.
- V2 projection: `2L + w_h(S_h-L) + w_a(C_a-L) + w_a(S_a-L) + w_h(C_h-L)`.
- **V3 projection, the only challenger:** `2L + 0.5 * [w_h(S_h-L) + w_h(C_h-L) + w_a(S_a-L) + w_a(C_a-L)]`. This is exactly the league mean plus the mean of the two teams' shrunken historical game-total deviations. All parameters are fixed: 450, 30, 5, 20, 0.5.

No odds, market-anchored adjustment, lineup oracle, opponent future result, dynamic feature or manual direction balancing. This design changes only the research forecast; production V1 remains failed/WATCH.

## Exactly one planned evaluation

On the **already inspected** 2015–2021 date-only archive, use identical eligible rows to compare V3, pinned V2, rolling league climatology, and the archive's `close_over_under` column where present (170–270 reference bound inherited from V2). Report:

1. Total normalized/scored/paired games and distinct paired dates, plus SHA check.
2. V3, V2, climatology and indicative reference RMSE on identical paired rows; V3 minus V2 and V3 minus indicative-reference **mean squared error**.
3. Per-season 2015–2021 breakdown (no best-season selection), signed model-minus-reference mean and exact model UNDER/OVER/tie counts.
4. Paired MSE difference uncertainty by a **750-replicate calendar-day cluster bootstrap with seed 17** (not independent formal validation).
5. Exact-holdout sample parity and any refusals. If the same cohort cannot be reconstructed, fail the comparison rather than silently trim it.

Descriptive research dispositions:
- `EXPLORATORY_BETTER_THAN_V2_AND_INDICATIVE_REFERENCE` only when both V3 paired RMSEs are strictly lower and both predeclared day-bootstrap 95% upper bounds for paired MSE differences are below zero.
- `EXPLORATORY_BETTER_THAN_V2_ONLY` if V3 paired RMSE strictly beats V2 but fails the above dual-reference rule.
- Otherwise `EXPLORATORY_NOT_BETTER_THAN_V2`.

Because the **same dates were observed in V1/V2 diagnoses** and the supposed SBR closing odds lack verified bookmaker, quote timestamp and pre-tip identity, even the top exploratory disposition is **NOT a certified market beat, prospective validation, edge, Model_P or PLAY**. The entire 2015–2021 screen is exploratory reused-cohort evidence. Do not tune 0.5 after observing it or retest a chosen subcohort. Any future V4 requires new preregistration and genuinely untouched/PIT-authenticated evaluation.

## Operational and governance boundary

Only a new, independent read-only research runner, tests and generated negative/positive report may follow. Do not touch protected freeze/evaluator, registry, live pricing/card, OddsPapi provider, historical acquisition workflow or future selection credit. A later independently verified, governed market study is separately required for any production decision; Rocky/Muse retains merge authority.
