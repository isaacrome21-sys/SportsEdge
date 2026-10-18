# Pre-registration: NBA quarter sim margin-dispersion (OT) adjustment, untouched 2026-27 evaluation

Committed **before** any 2026-27 NBA outcome is fetched, and before any code for this experiment is written. Authorized by ChatGPT's ruling on #2147 (Oct 13, 2026) as a **separate research experiment**. It does not override or rescue the failed (b) OT_FIX arm in `NBA_QUARTER_SIM_FROZEN_CAL_AND_OT_FIX_RESULT_20261013.md`, which stays FAIL.

**Governance flag:** new pre-registration path; needs ChatGPT freeze-inventory registration. Research only. No promotion, no PLAY, no betting eligibility under any outcome. Lines are naive stand-ins; the market baseline is MISSING; rest_adj = 0; ERA/form/rest corrections stay disabled.

## Disclosure (what is already known)
- 2024-25 and 2025-26 have both been examined. On 2025-26, `c = 0.60` (grid boundary) gave ML Brier 0.2084 → 0.2037 and log-loss 0.6060 → 0.5959 vs V1, and sim OT 3.23% vs 4.46% actual. That ML gain was unplanned, and is the motivation here, not evidence.
- Because both prior seasons are seen, **2026-27 is the only valid evaluation season.** No 2026-27 outcome has been loaded by this lane as of this commit.

## Arms (identical games, ratings, seeds, n_paths = 3000, naive lines, scoring)
- **Comparator — FROZEN_CAL:** V1 `simulate` with quarter calibration frozen from all 2024-25 and 2025-26 quarter games (the (a) FROZEN_CAL construction, refit on both seasons). No margin-dispersion factor (`c = 1`).
- **Challenger — FROZEN_CAL + MD:** identical, plus the regulation-quarter margin-dispersion factor `c` exactly as defined in the earlier prereg: per quarter and path `m = (h−a)/2`, `s = (h+a)/2`, `m' = E[m] + c·(m − E[m])`, `h = s + m'`, `a = s − m'`, rounded, floored at 0. Overtime periods untouched.
- Ratings: the as-of in-season walk-forward from #2147, unchanged. A game is scored only if both teams have ≥ 10 prior 2026-27 games.

## Parameter selection (frozen before 2026-27)
- Fit data: 2024-25 and 2025-26 only, using each season's V1-style walk-forward with the frozen calibration above.
- Grid: `c ∈ {0.30, 0.32, …, 1.00}` (36 values; widened from 0.60–1.00).
- Objective: minimize pooled (both seasons) **moneyline log-loss**. Ties (to 4 decimals) go to the larger `c`.
- **Boundary rule:** if the selected `c` is 0.30 (the lower edge), the grid is **not** extended again. The run proceeds with `c = 0.30`, and the result can be at most `INCONCLUSIVE_BOUNDARY`, never PASS_RESEARCH.
- The selected `c`, the full fit curve, and the fit-season OT rates are committed **before** any 2026-27 outcome is fetched. `c` is then frozen.

## Evaluation window and data
- 2026-27 regular season only, all games final. Free NBA/ESPN sources already used by #2147. No paid data, no backfill of other seasons.
- One evaluation run after the regular season ends. No interim looks at outcomes.
- If fewer than 900 games are scorable, the result is `INCONCLUSIVE_SAMPLE`.

## Metrics
- **Primary:** moneyline Brier and moneyline log-loss.
- **Secondary (reported, gating only as stated below):** sim OT frequency vs actual 2026-27 OT frequency; full-game TOTAL, H1 and Q1 Brier/log-loss; mean (sim − actual) total.
- Uncertainty: paired game-level bootstrap of the challenger − comparator ML Brier difference, 2,000 resamples, seed 20261013.

## Decision (fixed)
`PASS_RESEARCH` iff **all** hold:
1. Challenger ML Brier < comparator ML Brier, **and** challenger ML log-loss < comparator ML log-loss;
2. the 95% bootstrap interval for the ML Brier difference lies entirely below 0;
3. no Brier regression > 0.002 on TOTAL, H1 or Q1;
4. |mean (sim − actual) total| does not grow by more than 0.5 points;
5. `c` was not selected at the 0.30 boundary.

Otherwise `FAIL` (or `INCONCLUSIVE_BOUNDARY` / `INCONCLUSIVE_SAMPLE` as defined). OT frequency is reported regardless; matching it is not claimed by a PASS. Results are reported in full under every outcome. A PASS changes nothing about promotion or betting eligibility; it only justifies further research against real market prices.
