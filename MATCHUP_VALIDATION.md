# Matchup-adjustment hotfix — validation report

Branch: `feat/team-half-participation-20261011` (stacks on
`origin/feat/team-half-pricing-20261011`). Date: 2026-10-11.

## 2026-10-11 refinement: 538-adapted empirical calibration
Branch: `feat/qb-sp-adjustment-20261011` (stacks on the hotfix above).

The declared penalties (-3.0 QB total, ERA-vs-staff suppression) were replaced
with empirically calibrated 538-adapted adjustments. Methodology sources
actually read (not from memory):
- FiveThirtyEight "How Our MLB Predictions Work" (archived 2022-04-07, read
  in full): gameScore formula, rolling rGS per pitcher and per team,
  ratingAdj = 4.7*(pitcher_rGS - team_rGS), opener rule, HFA/travel/rest
  values, preseason construction.
- FiveThirtyEight NFL QB-adjustment: the archived methodology page's
  QB-adjustment section was unavailable (archive fetch failed; not retried
  per instructions). The published VALUE formula, the 10-game/20-game update
  rules, the defense adjustment, and the VALUE*3.3=Elo conversion were
  corroborated from two independent secondary sources quoting the
  methodology text plus the fivethirtyeight/data nfl-elo README column spec
  (qb1_value_pre = "raw Elo value", qb1_adj = "Elo adjustment").
- 538's own APIs (projects.fivethirtyeight.com) are dead post-shutdown
  (redirect to ABC News); the published per-game CSVs could not be fetched.
  All calibration was therefore done directly from free primary data
  (nflverse, MLB StatsAPI), which is strictly better for the point-in-time
  bar anyway.

### NFL QB adjustment (sportsedge/qb_value.py)
Per-game 538 VALUE from nflverse box scores with the published coefficients,
defense-adjusted via rolling team VALUE-allowed, rolling 10-game-block
ratings (Rating_new = 0.9*old + 0.1*mean(block), init 0 = replacement).
Fit on clean backup-start games 2015-2020 (n=599, week-1 excluded,
point-in-time clean):
- total_QB_effect = -0.014 + 0.1176 * (backup_rating - starter_rating)
- Empirical mean backup-start total effect: -0.582 (Tier-2 constant).
- Sanity: fitted slope 0.1176 own-team pts/VALUE-pt vs 538's implied
  3.3/25 = 0.132 spread pts/VALUE-pt -- independent corroboration.
Out-of-sample eval 2021-2024 (n=533), MSE of own-team-points residual:
  no adjustment 90.48 | declared -3.0: 96.26 (WORSE than nothing) |
  calibrated constant 90.20 | per-QB VALUE 87.45. Both-rated subset (n=312):
  per-QB 83.84 vs declared 93.09.
VERDICT: PASS. The declared -3.0 was actively harmful; the per-QB version
wins. Tier 1 (backup verifiable via nflverse depth charts) ships as primary;
Tier 2 (calibrated constant) is the fail-closed fallback. Doubtful = 50% of
the OUT extra remains DECLARED (no doubtful cases in 538's published data).
CFB keeps declared -1.5/-0.75, audit-flagged UNCALIBRATED (no 538 analog).

### MLB SP adjustment (sportsedge/mlb_sp_rgs.py)
Per-start 538 game scores from free StatsAPI boxscores (9,713 games,
2021-2024), trailing 20-start rGS vs trailing league mean (51.54).
Ablation (fit 2021-2022, eval 2023-2024 identical n=8800):
  no adjustment 10.1328 | old ERA-vs-staff formula 10.3608 (WORSE) |
  V1 team+oppnorm 10.1134 | V3 team+raw 10.1168 |
  V2 league+raw 10.0472 | V4 league+oppnorm 10.0387.
Shipped: V2, opp_total_adj = 0.014 - 0.0699*(pitcher_rGS - 51.54), cap +-2.0.
V4 was within noise (+0.08%) but needs ~20 extra fetches per starter;
opponent/park normalization is a documented known gap, not a silent
omission. The old ERA formula's flaw (vs own staff ERA) is fixed by
construction: the baseline is the league, not the staff.
VERDICT: PASS (beats no-adjustment and the old formula out-of-sample).

### Regression harness cases (the two withdrawn cards)
tests/test_matchup_regression_cases.py replays both flawed games:
- Lamar-out Ravens 1H ML +140: BEFORE (QB-blind) EV +$0.148 (fake edge
  reproduced); AFTER Tier-1 EV -$0.019 (study-pinned values); feed down ->
  QB_PARTICIPATION_UNVERIFIED (blocked). Live end-to-end (real nflverse
  weekly 2015-2026 + depth chart, no stubs): Lamar rating 49.19 (107 games),
  Huntley 5.42 (27 games), gap -43.78, total effect -5.16, extra -3.66 --
  the honest empirical answer is larger than the declared -3.0, in the
  direction the market moved.
- Skubal/Misiorowski team totals (real 2026 gameLogs: Skubal rGS 62.02,
  Misiorowski 66.72): BEFORE (pitcher-blind) Brewers TT OVER 3.5 EV +$0.043;
  AFTER rGS-adjusted EV -$0.020; feed down -> PROBABLE_PITCHER_UNVERIFIED.
Both flaw classes now flip from fake-edge to correctly-priced/blocked.

### Remaining limitations (honest)
- QB: the live Tier-1 path now uses nflverse weekly CSVs for ALL seasons
  (stats_player release carries weekly files for the current season), so no
  play-by-play download is needed. Early-season ratings (<10 games) sit at
  the replacement prior by design. The injury-feed starter is cross-checked
  against the depth-chart QB1 (last name + first initial); any identity
  break -> Tier-2, never a mismatched rating.
- SP: park factors not wired; bullpen-after-starter not separated (the
  regression estimates the total effect on the team total, which is the
  correct estimand for team totals).
- No market baseline leg (no historical odds); market-blind discipline kept:
  no market prices were used as features anywhere in the calibration.
- Nothing here is a validated betting edge: the harness measures
  calibration of means, not profitability.

## What was wired (original hotfix, 2026-10-11)

`sportsedge/team_half_pricing.py` previously built home/away score means from
base prior + HFA + recent-margin proxy only. It now carries a **required
matchup-adjustment audit** on every priced market:

- **NFL / CFB**: `free_models.injury_points` is called for both teams (the
  same call `free_models.calculate` uses for full-game pricing), plus an
  explicit starting-QB scan of the structure-verified ESPN injury feed.
  Verified QB OUT → declared −1.5 backup-replacement penalty on top of the
  generic −1.5 QB injury term (total declared effect −3.0 team points, NOT
  calibrated). Verified DOUBTFUL → −0.75. Unverifiable QB participation →
  refused with `QB_PARTICIPATION_UNVERIFIED`.
- **NBA**: `injury_points` wired; unverifiable → `PARTICIPATION_UNVERIFIED`.
- **MLB**: starting-pitcher adjustment is REQUIRED. Probable pitchers verified
  from `https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher`
  (`games[].teams.{home,away}.probablePitcher.{id,fullName}`); each starter's
  season ERA (min 5 GS) verified from `/people/{id}/stats?stats=season&group=pitching`,
  compared vs his own club's season staff ERA (`/teams/{id}/stats?...`).
  `suppression/9 = clamp(staff_ERA − pitcher_ERA, ±1.5)`; the OPPOSING team's
  total moves by `−suppression/9 × (avg IP per start / 9)`, bounded ±2.0 runs.
  Missing/unverifiable probable pitcher or opener shape → refused with
  `PROBABLE_PITCHER_UNVERIFIED`.
- Every priced result carries `matchup_audit` (per-team factor, points,
  statuses, and a `coverage.verified_applied` list). Missing critical factor
  is never silently priced.

All sources are free public endpoints, zero API keys. Formulas, source
hierarchy (official inactives > ESPN injury feed > nflverse fallback; never
rumors), and limits are documented in the module docstring.

## Validation performed

1. **Unit tests** (`tests/test_team_half_pricing.py`, 24 tests, all pass):
   injury_points wiring shifts means; QB OUT/DOUBTFUL apply the declared
   penalties; non-QB injuries don't trigger the QB term; unverifiable
   participation refuses with the explicit reason codes (NFL/CFB/NBA);
   MLB probable-pitcher adjustment shifts means in the right direction with
   sane magnitudes (Skubal/Misiorowski-style scenario); missing probable
   pitcher and opener (<5 GS) refuse; bad starters raise (not lower) the
   opposing total; first-half markets inherit adjusted means; all pre-existing
   team-half tests and the runner routing test still green.
2. **Harness experiment** (`/tmp/validate_matchup.py`, run with cwd at the
   backtest repo): 15 real recorded 2024 NFL games, chronological
   walk-forward splits, real final scores, production `_build_means` code path
   for both models, full-game TOTAL OVER at the existing model's projected
   total, settled by the harness.
   - Wiring check: the labeled synthetic QB-out scenario moved the away mean
     by exactly −3.0 on all 15 fixtures through the production path.
   - The candidate (false-premise QB-out on games where QBs actually played)
     scored worse than existing (Brier 0.3218 vs 0.2591), which is the
     EXPECTED direction-correct outcome: the adjustment is consequential and
     moves probability mass the right way; it is not evidence for or against
     real-world efficacy.

## Red-team findings (fixed in this branch)

Adversarial review ("try to break it") found and fixed two real gaps:

1. **Stale probable / late scratch**: if the schedule feed reports the game
   as anything other than `Scheduled`/`Pre-Game` (e.g. `In Progress`) while
   our kickoff is still in the future, the probable listing cannot be
   trusted -> now refused with `PROBABLE_PITCHER_UNVERIFIED`. Residual,
   documented: a scratch between our fetch and first pitch is not detectable
   from this endpoint; the audit records probable identity + schedule date
   for post-game reconciliation.
2. **De-facto opener**: a 5-start "probable" averaging under 4.0 IP/start is
   refused as opener/bullpen shape instead of being clamped upward.

Permanent regression tests now encode tonight's two withdrawn cards
(LAMAR-OUT, SKUBAL/MISIOROWSKI) plus 16 red-team cases: caps, GS boundary,
malformed innings/ERA, doubleheaders, TBD ids, non-dict payloads, QB
questionable/dict-status/two-QBs-out, ambiguous grouped payloads.

## Verdict: CONDITIONAL_PASS (not production-ready on efficacy)

The wiring, direction, magnitude sanity, and fail-closed behavior are
validated. Real chronological out-of-sample efficacy is NOT yet measured:

- **Gap 1 — QB adjustment**: no free historical QB-start/inactive sample is
  available in this environment, so improvement on true backup-QB games is
  unmeasured. Planned path: nflverse weekly injury CSVs (already a repo
  source pattern in `sportsedge/sports/nfl/injury_report_source.py`) joined
  PIT-correct by `date_modified` ≤ `as_of` — coordinator follow-up.
- **Gap 2 — pitcher adjustment**: historical probable-pitcher + PIT ERA data
  could not be retrieved here (StatsAPI is policy-blocked for the fetch
  tools in this environment; per instructions the block was not bypassed),
  so the pitcher adjustment is unit-validated only.
- **Gap 3 — market baseline**: no archived market prices; the market-baseline
  leg of Isaac's bar was not checked (Odds API keys are now authorized for
  the archival/evaluation side only — future baseline work).

Per the standing bar, these factors stay research-grade (declared,
unvalidated magnitudes) until the gaps close with a harness PASS.
