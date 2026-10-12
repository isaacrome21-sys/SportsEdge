# Matchup-adjustment hotfix — validation report

Branch: `feat/team-half-participation-20261011` (stacks on
`origin/feat/team-half-pricing-20261011`). Date: 2026-10-11.

## What was wired

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
