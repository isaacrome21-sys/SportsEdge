# NBA feasibility — Phase 5 (2026-10-11)

Branch: `feat/nba-20261011` (from `origin/main` 5e161b9).
Season context: 2026-27 NBA season tips ~Oct 20, 2026; assessment run Oct 11, 2026.

Standing bar (Isaac): public verified data only (ESPN APIs); no Odds API;
no generic league priors for player props; fail closed with explicit reason
codes; research-only, no betting authority; nothing called "verified" until it
passes the backtest harness.

## 1. What was verified live today

All endpoints below were hit live on 2026-10-11 and their response shapes
recorded as fixtures in `tests/fixtures/nba/` (see `README.md` there).

| Endpoint | Verdict | Notes |
|---|---|---|
| `site.api.espn.com/.../basketball/nba/scoreboard?dates=YYYYMMDD` | VERIFIED | Same event shape as football: `events[]` with `competitions[0].competitors[]` (`homeAway`, `team.id`, `score`), `status.type.completed`. 10 games on 2024-10-23 opening night. Final scores only — no period data. |
| `site.api.espn.com/.../basketball/nba/teams` | VERIFIED | 30 teams; registry hard-coded from the live response (`NBA_TEAMS` in `espn_verified_source.py`). NB: ESPN abbreviations are `GS`, `NY`, `UTAH` — copied verbatim, not "corrected". |
| `site.api.espn.com/.../basketball/nba/teams/{id}/roster` | VERIFIED | Current-season roster; `athletes[]` are athlete objects directly (no `items` wrapper). Used for identity verification. |
| `site.web.api.espn.com/apis/search/v2?query=..&type=player` | VERIFIED with caveat | Returns the athlete id inside `uid` (`s:40~l:46~a:1966`); `defaultLeagueSlug: "nba"` confirms league. **Team subtitle was observed stale live** ("Philadelphia 76ers" for LeBron James, who was on LAL) — search team labels are never trusted; roster membership is required. |
| `site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog` | VERIFIED | **The `site.api` v2 gamelog path 404s for NBA** — the working path is `site.web.api/.../common/v3` (same host family as the NFL path). Shape: top-level `events` is a **dict keyed by eventId** (not a list); per-game stats live in `seasonTypes[].categories[type=="event"].events[]` as `{"eventId","stats":[strings]}` aligned to top-level `names`; `type=="total"` categories are summaries and are skipped. 14 columns incl. `minutes`, `points`, `totalRebounds`, `assists`, `threePointFieldGoalsMade-threePointFieldGoalsAttempted`, `blocks`, `steals`. `?season=YYYY` selects the season ending in YYYY (2025 → 2024-25). LeBron 2024-25: 70 regular-season games decoded — matches reality. |
| `site.api.espn.com/.../basketball/nba/summary?event={id}` | VERIFIED | `header.competitions[0].competitors[].linescores` gives 4 quarter scores; quarter sums reconciled against the final (fail-closed on mismatch). This is the verified period-score source. `boxscore.players` additionally carries per-game per-player stats with athlete ids (useful cross-check, not yet wired). |

## 2. Game markets — minimal verified path (built)

New modules in `sportsedge/sports/nba/`:

- `espn_verified_source.py` — `NBASource`: fixture resolution (unique pregame
  fixture on the scoreboard, 3h tipoff window), `parse_completed_games`
  (completed-only, registry-verified team ids, fail-closed scores),
  `quarter_scores` (reconciled quarter history), roster/search identity.
  All-Star exhibitions (special team ids like 130579 "Team Chuck") are
  rejected by the registry; `parse_completed_games(..., skip_unregistered_teams=True)`
  skips them explicitly for backtests.
- `nba_game_market_pricing.py` — ratings fit on verified games
  (`ratings_model.replay`, chronological, results-only), residual sigmas from
  train, then normal-CDF prices for MONEYLINE / SPREAD / TOTAL
  (`price_game_markets`, `spread_probability`, `total_probability`).

End-to-end proof: 35 new unit tests, all on recorded fixtures
(`tests/test_nba_espn_verified_source.py`,
`tests/test_nba_gamelog_decode.py`,
`tests/test_nba_public_player_history.py`,
`tests/test_nba_game_market_pricing.py`); full NBA suite 133/133 green.

### Harness validation (run 2026-10-11, cwd=`~/workspace/sportsedge-backtest`)

Script: `scripts/validate_nba_game_markets.py` (imports the harness by package
path; loads branch modules under a synthetic `branch_nba` package — neither
repo modified, nothing copied into the branch).

- 310 real 2024-25 games (every 4th day 2024-10-23→2025-04-10, cached under
  `data/backtest_nba_cache/`), 16 walk-forward splits
  (min_train=120, test_size=40, embargo 1 day), PIT-safe (`as_of` = tipoff−60m,
  model fits on train only).
- Candidate: the branch's verified path. Existing: naive (train home-win-rate
  for ML; train league averages for margin/total). Market baseline: MISSING
  (no Odds API by Isaac's choice).
- **Verdict: CONDITIONAL_PASS** — candidate beats naive on Brier
  (0.2364 vs 0.2473) and log-loss (0.6652 vs 0.6877), n=1306; calibration
  roughly monotone. Spread/total as MAE diagnostics only (no market lines to
  settle binary outcomes): margin 11.83 vs 12.37 naive; total 14.36 vs 15.08.
- Full report: `docs/NBA_HARNESS_VALIDATION_2026-10-11.md`.

CONDITIONAL_PASS is **not** a validated edge. Per the harness contract: "Do
not promote on this verdict alone." No NBA market is SUPPORTED for betting.

## 3. Player-prop feasibility assessment

### Verified (implemented + unit-tested)

- **Endpoint + shape**: `nba_gamelog_decode.py` decodes the live-verified shape
  (events-dict, seasonTypes/categories, names-aligned stats). Only unambiguous
  columns: `minutes`, `points`, `rebounds`, `assists`, `threes_made`
  (from "4-9" pairs), plus `blocks`, `steals`, `fouls`, `turnovers`.
- **Identity**: `NBASource.resolve_athlete` — fixture-roster first (unique
  exact-name match on one of the two fixture teams), ESPN search fallback with
  mandatory roster-membership confirmation. Ambiguity or no roster membership
  → fail closed (`NBA_PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH`,
  `NBA_SEARCH_HIT_NOT_ON_FIXTURE_ROSTER`).
- **≥N-games gate**: `nba_public_player_history.py` requires
  `MIN_PRIOR_GAMES = 5` verified regular-season games before tipoff and before
  `as_of`; multi-season `?season=` span so the gate is reachable early in the
  season. Preseason/postseason excluded (different rotations), counted
  separately. Per-game `played_for_team_id` + `team_points` recorded from the
  event meta (handles traded players).
- **Role-fitter feed**: `to_box_observations()` converts collector output to
  `NBAPlayerBoxObservation` rows for the existing `fit_player_role`.

### NOT_WIRED (with reasons)

- **Prop pricing (all player markets)**: the harness has no player-prop
  settlement leg (ML/SPREAD/TOTAL only), and the minutes/role projection model
  (`player_stats.py` simulation) is unvalidated out-of-sample. Emitting
  probabilities would violate the standing bar. Status stays NOT_WIRED until a
  player-prop settlement path exists and the role model passes the harness.
- **Double-doubles / triple-doubles**: all five counting columns are verified
  in the gamelog, so observation is possible, but pricing needs joint-threshold
  calibration that is unvalidated → NOT_WIRED.
- **First basket / race to X / exact score**: need tip/first-possession or
  play-by-play event data; no verified free endpoint is wired → NOT_WIRED.
- **Injury/lineup context for props**: no verified free NBA injury feed is
  wired in this phase; the existing `availability.py` snapshots require a
  caller-supplied source → props cannot account for news without manual input.

### Feasibility verdict

Player-prop **data collection is feasible and verified end-to-end** from free
ESPN endpoints (no other source needed). Player-prop **pricing is NOT feasible
yet** under the standing bar: it is blocked on (1) harness player-prop
settlement and (2) out-of-sample validation of the role/minutes model. The
per-player stat columns needed for points/rebounds/assists/threes/steals/
blocks/PRA all exist in the verified gamelog — the gap is validation, not data.

## 4. Coverage classification (master matrix: `market_coverage_dk.md`, NBA section)

SUPPORTED = verifiably working end-to-end **and** harness-validated. Nothing
below is SUPPORTED — no NBA market has a validated edge.

| Market group | Status | Reason |
|---|---|---|
| Game moneyline | IN_BUILD | Data path + pricing verified end-to-end on recorded fixtures; harness CONDITIONAL_PASS vs naive (market baseline missing). Not a verified edge. |
| Spread (+ alternates) | IN_BUILD | Priced from the same verified margin distribution; alternates are the same read-out at different lines. Binary settlement vs market lines not validated (no lines source). |
| Totals — game | IN_BUILD | Same as spread, via the verified total distribution. |
| Totals — team | IN_BUILD | Derivable from home/away point distributions; per-team sigma decomposition unvalidated. |
| Totals/spread — half & quarter | IN_BUILD | Quarter-score history verified via the summary endpoint (reconciled); period-level pricing model not yet built/validated. |
| Player props — points | NOT_WIRED_WITH_REASON | History collection verified (gamelog + identity + ≥5 gate); pricing blocked — no harness player-prop settlement, role model unvalidated. |
| Player props — rebounds | NOT_WIRED_WITH_REASON | Same as points. |
| Player props — assists | NOT_WIRED_WITH_REASON | Same as points. |
| Player props — threes | NOT_WIRED_WITH_REASON | Same as points. |
| Player props — steals | NOT_WIRED_WITH_REASON | Stat column verified in gamelog; pricing blocked (same as points). |
| Player props — blocks | NOT_WIRED_WITH_REASON | Stat column verified in gamelog; pricing blocked (same as points). |
| Player props — double-doubles | NOT_WIRED_WITH_REASON | Observable from verified columns; joint-threshold calibration unvalidated. |
| Player props — PRA (PR/PA/RA) | NOT_WIRED_WITH_REASON | Columns verified; same-path derivation exists in research modules but is unvalidated. |
| Game props — first basket | NOT_WIRED_WITH_REASON | Needs tip/first-possession event data; no verified free endpoint wired. |
| Game props — race to X | NOT_WIRED_WITH_REASON | Needs play-by-play; no verified free endpoint wired. |
| Game props — exact score | NOT_WIRED_WITH_REASON | Joint score distribution unvalidated; no verified path demonstrated. |
| Live / in-game | NOT_WIRED_WITH_REASON | Master matrix scopes live out for the NBA pregame engine; Isaac's live directive is a separate coordinator phase. |
| Futures | NOT_WIRED_WITH_REASON | Out of scope per master matrix (needs long-horizon modeling). |
| Same-game parlays | NOT_WIRED_WITH_REASON | Out of scope per master matrix (needs correlation modeling). |

## 5. Known limitations

- The harness ML leg emits HOME+AWAY complementary records per game (n=1306
  from 653 test games); comparison vs naive is apples-to-apples but the
  effective game count is 653.
- Ratings params are the module defaults (k=0.05, carry=0.6); no tuning was
  done in this phase — tuning without a market baseline risks overfitting to
  the naive leg.
- `minutes` in the gamelog are whole numbers (ESPN rounds); seconds-level
  precision is unavailable.
- Gamelog `?season=` covers the current + past seasons; the upcoming 2026-27
  season has no history yet — early-season props will hit the ≥5-games gate
  via 2025-26 history, with the usual early-season staleness caveat.
- All-Star exhibitions are excluded from game history by team-registry check;
  any future special-event team ids will fail closed (safe default) until
  explicitly handled.
- No market baseline exists anywhere in this phase (no Odds API); the best
  achievable harness verdict for any NBA model is CONDITIONAL_PASS.

## 6. Files

- `sportsedge/sports/nba/espn_verified_source.py` — verified ESPN acquisition
- `sportsedge/sports/nba/nba_gamelog_decode.py` — fail-closed gamelog decode
- `sportsedge/sports/nba/nba_public_player_history.py` — player history + gate
- `sportsedge/sports/nba/nba_game_market_pricing.py` — ML/spread/total pricing
- `tests/fixtures/nba/` — 7 recorded fixtures + provenance README
- `tests/test_nba_espn_verified_source.py`, `test_nba_gamelog_decode.py`,
  `test_nba_public_player_history.py`, `test_nba_game_market_pricing.py`
- `scripts/validate_nba_game_markets.py` — harness validation driver
- `docs/NBA_HARNESS_VALIDATION_2026-10-11.md` — harness report
- `data/backtest_nba_cache/` — 43 cached 2024-25 scoreboard pages
