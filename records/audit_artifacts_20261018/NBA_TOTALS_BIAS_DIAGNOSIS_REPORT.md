# NBA totals signed-bias diagnosis — REPORT

**Date:** 2026-10-18 · **Kind: DIAGNOSIS ONLY** (no model changed, no
fix scored, nothing tuned; plan frozen in `PLAN.md` before computing)
**Question:** Is the RAW NBA totals model systematically biased — does
it predict totals consistently higher or lower than reality and than
the closing line — and is any bias stable across seasons and segments?

## Verdicts (declared rule in PLAN.md)

| Series | Overall mean [95% CI] | Verdict |
|---|---|---|
| pred − actual (vs reality) | **−0.09 [−0.48, +0.28]** | **NO_BIAS** |
| pred − close (vs market) | **+0.38 [+0.21, +0.55]** | **BIAS_UNSTABLE** |

**Answer:** The raw totals model is **not** systematically biased
against reality: across 7,151 games (2015–2021) its average signed
error is −0.09 points with a CI spanning zero, and no individual
season's CI excludes zero. It does sit ~0.4 points **above the closing
line** on average, but that gap is significant in only 2 of 7 seasons
(→ unstable by the declared rule), and the arithmetic shows where it
comes from: actual totals beat the closing line by ~+0.47 points on
average over this span (actual − close = gap − err), i.e. **the close
ran low against reality in a rising-scoring era; the model tracked
reality**. There is no constant level bias in the model to fix — and
the descriptive check below shows a constant shift would have made
even in-sample accuracy slightly *worse*.

The real defect the diagnosis surfaces is **dispersion, not level**:
the model's predicted totals are overdispersed — its extreme
predictions regress hard (see pred-band table). That is a different
disease than the one this diagnosis was commissioned to find, and no
shift treats it.

## Model construction identified (pinned, not substituted)

- **Module:** `sportsedge/sports/nba/ratings_model.py` at main
  `a7bf4c748`, sha256
  `16e3304718703bcf4ba901fd9bb97b4712d3994d1314f93d93dc19e4bd63ad20`
  (working-tree copy verified byte-identical to that commit).
- **Prediction:** `NBARatings.predict(home, away)` → (home_pts,
  away_pts); **predicted game total = home_pts + away_pts** (identically
  `margin_total(home, away)[1]`), state walked in date order by
  `replay()`, every prediction strictly pre-game, scores-only inputs.
- **Parameters:** committed defaults `NBARatingsParams()` — k=0.05,
  k_league=0.01, k_hca=0.002, carry=0.6, init_league=100.0,
  init_hca=3.0.
- This is exactly the candidate the Oct 18 sweep scored for B4 team
  totals / B11 quarter totals (`backtest_everything_20261018`,
  SPEC_NBA_GAME_LEVEL_V1). **Replication anchor:** my replay reproduces
  that run's gated game count exactly — 7,753 games (= its 15,506 B4
  team-game rows ÷ 2) — under its declared gates (seasons 2015–2021,
  both teams ≥10 prior in-season games, league ≥200 prior in-season
  team-games, raw archive team strings).
- NOT this construction: (a) the shipped card pricing path — out of
  scope, not diagnosed; (b) the sibling v1 study's grid-searched
  parameterization (k=0.04 / carry=0.5 / k_league=0.005,
  `scripts/backtest_nba_ratings_vs_lines.py`) used for the carried
  B1–B3 verdicts — a different parameterization of the same module,
  deliberately not used here. Cross-check only: its recorded total MAE
  is 14.58; this run's MAE vs actual is 14.58 (different game sets and
  parameters; the two parameterizations' totals accuracy is
  indistinguishable at two decimals).

## Data (all hashes recorded)

| File | sha256 |
|---|---|
| SBR archive `data/nba_archive_10Y.json` (flancast90/sportsbookreview-scraper, re-cloned 2026-10-18) | `0c9858489d224c54dcf2f2d1b70c3a122675381d35ae03ce0a81204f739f0e98` — **identical to the hash the Oct 18 run recorded**, so this is the same archive bytes |
| hoopR team boxscores `team_boxscores_2016.csv` | `3b22105aa93fdee4755163f759cac779be5f92568c84fb846d60b9d6fb4cb9a9` |
| `team_boxscores_2017.csv` | `f904d459a973408a0eb9e5f81a61d6b878d27f1ad63ec8920d40a4c6ec9bf322` |
| `team_boxscores_2018.csv` | `491301f9b71053486610ff19057ead4ce0c35b2844fd7ef019499630e39f9131` |
| `team_boxscores_2019.csv` | `8db4b820aa542ce895b95c04faae6a6c9b7afe6e44ce9ea2b5a633c48e948908` |
| `team_boxscores_2020.csv` | `4503d31bc0e85fbe39e17f5edf8dd6bdcd8c3cc205f3f0fa79197ad77cee0709` |
| `team_boxscores_2021.csv` | `04fcbdb1dbad4dc6e5260fff870df78aab1ed000b5713b4dbd4afa1e1176712a` |
| `team_boxscores_2022.csv` | `af46dd3d3e6c73c29b3747c4a1fdbf3d911296118036365153a8dfedd4891c17` |
| Joined actuals `data/hoopr_actuals.csv` | `568089129772e100cbe0fd48dccde1f692e24e249d9ab1c8ab5030a3ba9f7190` |

Actuals note: no hoopR results file for this span existed in the
workspace (exhaustive search — the only NBA results data present is
ESPN 2024-25 player gamelogs). The actuals were therefore staged from
the same source family the project adopted for NBA results (§21 /
PR #2402): the sportsdataverse-data release assets
`nba_stats_team_boxscores/team_boxscores_{season-end-year}.csv`
(hoopR's NBA Stats team-boxscore dataset; same release host as the
repo's merged `scripts/pull_nba_results.py`). Per that project's own
precedent this is a spot-check-grade source, not a season-level
verification — see the join cross-check below for the empirical check
performed here.

**Sample flow:** 13,903 archive games → 7,753 pass the warmup gates
with a prediction → 7,172 also have a valid closing total
(`close_over_under` in [170, 270], the sibling script's declared
window; 581 dropped) → **7,151 joined to hoopR actuals** (21 lost: the
seven count-mismatched Finals pairings below).

**Join design + QA:** hoopR team rows carry game_id, side, tricode,
points — no date. Within each (season, home, away) pairing, hoopR games
in game_id order were paired with archive games in date order, k-th to
k-th; **final scores were never used in matching**, only compared
afterwards. One archive defect had to be handled join-side: in season
2019 the archive dates Jul–Oct **2020** bubble games with the
season-start year (a Finals game played 2020-08-21 is dated
2019-08-21); any season-2019 date before the 2019-10-22 tipoff is such
a game and was ordered after the regular season by (month, day) —
calendar facts only. (The prediction replay itself keeps the archive's
raw order, exactly as the Oct 18 run did — the quirk is part of the
run being diagnosed, and is disclosed as such.) Results of the
cross-check after that correction: **hoopR and archive finals agree on
7,142 of 7,151 analysis games (99.87%)**; the 9 disagreements (2016: 1,
2020: 7, 2021: 1) are the ordinary reschedule-order slip class and are
retained, counted here. Seven Finals pairings (GSW–CLE 2015/16,
CLE–GSW 2017, GSW–TOR 2018, MIA–LAL 2019, MIL–PHX 2020, BOS–GSW 2021)
have one more hoopR game than archive rows and were left entirely
unmatched (conservative; 21 analysis-eligible games). Six archive rows
with team label "0" (one per season) cannot join and were excluded
join-side only.

## Bias tables

Bootstrap: paired ISO-week block bootstrap over game dates, 2,000
resamples, seed 20261018 (harness convention). Means are the verdict
statistic per PLAN.md; medians reported alongside.

### pred − actual (negative = model low vs reality)

| Segment | n | Mean | 95% CI | Median |
|---|---|---|---|---|
| **Overall** | 7,151 | **−0.09** | [−0.48, +0.28] | +0.61 [+0.02, +1.09] |
| 2015 | 1,071 | −0.26 | [−1.18, +0.70] | +0.36 |
| 2016 | 1,048 | −0.12 | [−1.05, +0.82] | +0.53 |
| 2017 | 1,081 | +0.02 | [−0.97, +0.99] | +1.16 |
| 2018 | 1,079 | +0.19 | [−0.93, +1.38] | +1.22 |
| 2019 | 896 | −0.42 | [−1.48, +0.57] | +0.82 |
| 2020 | 923 | +0.08 | [−0.75, +0.91] | −0.05 |
| 2021 | 1,053 | −0.17 | [−1.16, +0.95] | +0.08 |
| Close <215 | 3,058 | +0.32 | [−0.33, +0.95] | +1.15 |
| Close 215–225 | 2,386 | +0.09 | [−0.50, +0.67] | +0.45 |
| Close 225–235 | 1,402 | −1.17 | [−2.24, −0.08] | −0.09 |
| Close >235 | 305 | −0.71 | [−2.62, +1.27] | −0.82 |
| Pred <215 | 3,083 | −1.18 | [−1.80, −0.57] | −0.64 |
| Pred 215–225 | 2,333 | +0.30 | [−0.36, +0.95] | +0.78 |
| Pred 225–235 | 1,374 | +0.84 | [−0.07, +1.75] | +1.57 |
| Pred >235 | 361 | +3.18 | [+1.32, +5.03] | +3.34 |

Read: no season shows a level bias. The median game is predicted ~0.6
high while the mean is ~0 — the error distribution is left-skewed
(low misses are larger), not shifted. The monotone pred-band pattern
(−1.18 at the bottom, +3.18 at the top) is the overdispersion
signature: games the model calls extreme score closer to the middle
than it predicts, in both directions.

### pred − close (positive = model above the closing line)

| Segment | n | Mean | 95% CI | Median |
|---|---|---|---|---|
| **Overall** | 7,151 | **+0.38** | [+0.21, +0.55] | +0.25 [+0.07, +0.43] |
| 2015 | 1,071 | +0.33 | [−0.07, +0.77] | +0.27 |
| 2016 | 1,048 | +0.24 | [−0.13, +0.63] | +0.02 |
| 2017 | 1,081 | +0.23 | [−0.14, +0.59] | +0.13 |
| 2018 | 1,079 | +0.56 | [+0.05, +1.07] | +0.68 |
| 2019 | 896 | +0.88 | [+0.55, +1.24] | +0.69 |
| 2020 | 923 | +0.23 | [−0.37, +0.82] | +0.14 |
| 2021 | 1,053 | +0.27 | [−0.27, +0.85] | +0.02 |
| Close <215 | 3,058 | +0.77 | [+0.57, +0.98] | +0.55 |
| Close 215–225 | 2,386 | +0.40 | [+0.14, +0.64] | +0.32 |
| Close 225–235 | 1,402 | −0.24 | [−0.61, +0.12] | −0.37 |
| Close >235 | 305 | −0.74 | [−1.37, −0.18] | −0.77 |
| Pred <215 | 3,083 | −0.43 | [−0.66, −0.21] | −0.49 |
| Pred 215–225 | 2,333 | +0.49 | [+0.27, +0.71] | +0.47 |
| Pred 225–235 | 1,374 | +1.39 | [+1.09, +1.69] | +1.22 |
| Pred >235 | 361 | +2.74 | [+2.21, +3.26] | +2.61 |

Read: positive in all 7 seasons as a point estimate, individually
significant in only 2 (2018, 2019) → **BIAS_UNSTABLE** under the
declared rule (majority-of-seasons significance required). The
close-band flip (+0.77 low → −0.74 high) shows the model also
compresses *relative to the line*: the closing line is more dispersed
than the model's predictions at the extremes.

## Descriptive shift arithmetic — DESCRIPTIVE ONLY, NOT A FIX TEST

In-sample, on the same 7,151 games, shifting every prediction by the
measured overall bias (s = −0.09, i.e. pred + 0.09):

| Metric | Before | After shift |
|---|---|---|
| MAE(pred − close) | 3.021 | 3.027 |
| MAE(pred − actual) | 14.580 | 14.583 |

A constant shift equal to the measured bias would have changed nothing
for the better even on the data the bias was measured on — consistent
with there being no level bias to remove. This is arithmetic on seen
data; it is not evidence about any correction out of sample, in either
direction.

## Proposal

**NONE.** The precondition in the frozen plan — a stable bias — is not
met: NO_BIAS vs reality, and the vs-close gap is unstable across
seasons and explained by the close's own deviation from actuals plus
extreme-range compression, neither of which a constant shift
addresses. No frozen v2 shift spec is proposed, and nothing here
authorizes one.

What this diagnosis does and does not rule out, for the record:

- It kills the specific hypothesis "the raw totals model is
  systematically high/low, fix the level." The −8% to −11% market-leg
  losses reported for NBA totals are **not** explained by a level bias
  in this model — they live in the tails (overdispersion: the model
  takes extreme positions that regress) and in the market's own era
  drift, which a bettor cannot harvest by shifting the model.
- It does not vindicate the model: total MAE 14.58 vs the close's own
  accuracy remains the standing B3 picture (the close is the better
  predictor), unchanged by this diagnosis.
- Any future v2 aimed at the dispersion defect (e.g. shrinking
  predicted totals toward the league mean) would be a NEW
  construction under the version-scoring rule: preregistered, frozen
  before scoring, and scored on games it has not seen — a decision for
  the owner, not taken here.

## Files

- `PLAN.md` (sha256 `23a640ebe91e4a211994a25e7d001b4eb7e5aaa07233c7c487834b075a347bd9`) — frozen before computation
- `scripts/diagnose_nba_totals_bias.py` (`f1f58cee4e26dd01306c75650045b6575f18c7ee2d503e3541e96608826a3a70`) — asserts archive + module hashes at runtime
- `scripts/build_actuals.py` (`291372b30b3ab196bc50b6ced8abf8017a14cd9f4fc83b9541b1d533950d554b`)
- `results/nba_totals_bias_results.json` (`3cbf99302226491dbf9a474238f1f987d4c76cd2ddb175e82f7ab2b4b7789565`)
- `results/nba_totals_bias_scored_games.csv` (`f5fba4daec354bbf178157f93286690105a628df786db5be434100716e61aaf3`) — all 7,151 scored games
- `data/actuals_join_qa.json` — join QA detail
