# NBA totals signed-bias diagnosis — plan (written BEFORE any computation)

**Date:** 2026-10-18. **Kind: DIAGNOSIS ONLY.** No model changes, no
corrected model, no fix scored, nothing tuned. Historical archive only;
no 2026-27 data or captures touched.

## Question

Is the RAW NBA totals model systematically biased — does it predict game
totals consistently HIGHER or LOWER than (a) reality (actual final total)
and (b) the closing total line — and is any bias STABLE across seasons
and line segments?

## Pinned construction (the "raw model")

The construction the Oct 17–18 backtests scored for NBA team totals (B4)
and quarter totals (B11) in `backtest_everything_20261018`
(`specs/SPEC_NBA_GAME_LEVEL_V1.md`, `scripts/score_nba_game_level.py`):

- Module: `sportsedge/sports/nba/ratings_model.py` at main `a7bf4c748`,
  sha256 `16e3304718703bcf4ba901fd9bb97b4712d3994d1314f93d93dc19e4bd63ad20`
  (verified: the local clone's working-tree copy hashes identically).
- Prediction: `NBARatings.predict(home, away)` → (home_pts, away_pts);
  **predicted game total = home_pts + away_pts** (identically
  `margin_total(home, away)[1]`). State walked in date order by
  `replay()`; every prediction strictly pre-game.
- Parameters: **committed defaults** `NBARatingsParams()` —
  k=0.05, k_league=0.01, k_hca=0.002, carry=0.6, init_league=100.0,
  init_hca=3.0. (The sibling v1 study's grid-searched parameters
  k=0.04 / carry=0.5 / k_league=0.005 are a DIFFERENT parameterization
  of the same module, used for the carried B1–B3 verdicts; they are NOT
  used here and are not silently substituted.)
- Team identity: raw archive team strings, exactly as the Oct 18 scorer
  parsed them (no alias normalization).

## Data

- Lines + finals: public SBR archive `nba_archive_10Y.json` from
  github.com/flancast90/sportsbookreview-scraper — the exact source and
  file the Oct 18 run used. Provenance gate: the copy used MUST hash to
  sha256 `0c9858489d224c54dcf2f2d1b70c3a122675381d35ae03ce0a81204f739f0e98`
  (recorded in `backtest_everything_20261018/results/nba_game_level_results.json`).
  If no copy matches that hash, STOP and report instead of computing.
- Actual totals: hoopR / sportsdataverse results data already in the
  workspace, joined on game (date + teams); the archive's own finals are
  the cross-check. Join rate and any mismatches are reported; games that
  cannot be joined are excluded and counted.
- Closing total: archive `close_over_under`, valid iff 170 ≤ value ≤ 270
  (the validity window declared in the repo sibling script's
  `normalize()`).

## Analysis set

Replay over ALL archive games (2011–2021, state needs history), scored
only where ALL of the following hold (the Oct 18 run's declared gates):
season in 2015–2021; both teams have ≥10 prior in-season games; league
has ≥200 prior in-season team-games; valid closing total per above;
actual total available from the results join.

## Measurements

Per game: `err_actual = pred_total − actual_total`;
`gap_close = pred_total − close_total`.

Report mean and median with bootstrap 95% CIs (paired ISO-week block
bootstrap over game dates, 2,000 resamples, seed 20261018 — the harness
convention) for:

- overall pool;
- per season (2015…2021);
- by closing-line band: **[170,215), [215,225), [225,235), [235,270]**;
- by predicted-total band (same edges), if each band has n ≥ 100.

## Stability verdict (declared rule)

Applied separately to `err_actual` (primary — bias vs reality) and to
`gap_close` (secondary — bias vs the market):

- **NO_BIAS**: overall mean's 95% CI includes 0.
- **BIAS_STABLE**: overall CI excludes 0; a majority of individual
  seasons have CIs excluding 0 with the SAME sign as overall; and NO
  season whose CI excludes 0 has the opposite sign.
- **BIAS_UNSTABLE**: otherwise (bias present overall but sign or
  significance inconsistent across seasons).

## Descriptive shift arithmetic (NOT a fix test)

Let s = overall mean of `err_actual`. Report, on the same games:
MAE of `gap_close` before vs after replacing pred with pred − s, and
MAE of `err_actual` before vs after. Labeled **DESCRIPTIVE ONLY** —
in-sample arithmetic; it is not evidence a correction would work out of
sample and authorizes nothing.

## Final section rule

If (and only if) a stable bias is found, the report ends with a
PROPOSAL ONLY for a frozen v2 spec (declared shift rule + fit window) to
be scored exclusively on 2026-27 captured DK lines, for the owner's
ruling. Nothing is implemented.
