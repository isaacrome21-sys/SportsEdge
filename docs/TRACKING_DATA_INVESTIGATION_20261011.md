# Tracking-Data Investigation — Phase 3 (2026-10-11)

All probes run 2026-10-11 ~18:25 CT. Bar: **free AND stable AND verifiable**;
undocumented endpoints are never built upon. Wired sources ship with recorded
fixtures and fail-closed reason codes; nothing here feeds pricing yet — any
future pricing factor must pass the backtest harness (candidate vs existing vs
market baseline, chronological out-of-sample) before production use.

## WIRED

### 1. MLB StatsAPI game-feed pitch tracking — WIRED
- Endpoint: `GET https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live`
- Module: `sportsedge/mlb_statsapi_pitch_tracking.py`
- Free: yes, no key, no auth. Stable: same documented StatsAPI family already
  used for schedule/history; official docs at statsapi.mlb.com/docs.
- Verified: gamePk 849831 (2026-10-10, CHW@CLE, Final) → 257/257 pitch events
  carried `pitchData`; gamePk 717753 (2023-06-15, TOR@BAL, Final) → 278/278 —
  multi-year history available. `fields` filter slims ~700KB → ~16KB.
- Fields: `startSpeed`, `endSpeed`, `spinRate`, `spinDirection`, `breakAngle`,
  `breakLength`, `breakY`, `breakHorizontal`, `breakVertical`,
  `breakVerticalInduced`, `extension`, `plateTime`, `typeConfidence`, `zone`,
  full trajectory coordinates; pitcher identity from `play.matchup.pitcher`.
- Fail-closed: non-`Final` games refused (`PITCH_TRACKING_GAME_NOT_FINAL`);
  missing sections, empty feeds, and fetch failures raise explicit codes.
- Limits: per-game fetch (histories need one call per game); Final games only
  — live/in-progress belongs to the live phase, not this module.

### 2. nflverse Next Gen Stats releases — WIRED
- Endpoint: `https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{passing|rushing|receiving}.csv.gz`
- Module: `sportsedge/nflverse_ngs.py`
- Free: yes, no key. Stable: versioned release tag refreshed nightly
  in-season (observed update 2026-10-11); same pattern nflreadr uses since 2022.
- Verified: 6,103 passing rows, seasons 2016–2026, 2026 weeks 0–5 present.
  Documented data dictionary (nflreadr `dictionary_nextgen_stats`). Plain
  `csv.gz` — no new dependency.
- Fields (passing): `avg_time_to_throw`, `avg_completed_air_yards`,
  `avg_intended_air_yards`, `avg_air_yards_differential`, `aggressiveness`,
  `max_completed_air_distance`, `expected_completion_percentage`,
  `completion_percentage_above_expectation`, …; rushing/receiving per dictionary.
- Fail-closed: invalid stat type, fetch/gzip/CSV failures, missing schema
  columns, and no-prior-weeks all raise explicit `NGS_*` codes.
- `rolling_player_metrics` enforces strict no-lookahead: target week sees only
  strictly earlier weeks of the same season; `week == 0` summaries excluded.
- Limits: week-level only (no play-level tracking); players below attempt
  thresholds absent by design.

### 3. Baseball Savant statcast_search/csv — WIRED (legacy, grandfathered)
- Already wired in main by earlier work (`statcast_daily_source.py`, consumed by
  `mlb_pitcher_k_historical_*`, `mlb_run_it_pregame`). Probed alive 2026-10-11.
- Assessment: **undocumented** — no official API docs; stability is de-facto
  (pybaseball ecosystem) only. Under the strict bar it would be NOT_WIRED.
  Kept, not expanded; new Statcast-flavored acquisition must use the
  documented StatsAPI pitch-tracking source above. Flagged for Isaac's review.

## NOT_WIRED (with reason)

### 4. Official NFL Next Gen Stats API — NOT_WIRED / UNDOCUMENTED_ENDPOINT
- `api.nextgenstats.nfl.com`: unreachable from probe; no official public docs;
  historically schema-unstable and rate-limited. nflverse's republication is
  the verifiable path instead.

### 5. ESPN advanced metrics (QBR et al.) — NOT_WIRED / UNDOCUMENTED_ENDPOINT
- `site.api.espn.com` advanced surfaces have no public documentation;
  reverse-engineered shapes change without notice. Not built upon.

### 6. CFB player tracking — NOT_WIRED / NO_PUBLIC_SOURCE_EXISTS
- No free public player-tracking feed exists for college football. Nothing to wire.

### 7. CollegeFootballData advanced stats — NOT_WIRED / API_KEY_REQUIRED
- Documented OpenAPI, but the free tier needs a provisioned `CFBD_API_KEY`,
  unavailable here, so payloads could not be verified. Already wired for lines
  elsewhere. Team-level only — not tracking data regardless.

### 8. nflverse non-tracking datasets — NOT_WIRED / OUT_OF_SCOPE_DEFERRED
- `snap_counts`, `injuries`, `depth_charts`, `rosters`, `player_stats`,
  `officials`: documented, free, same stable release pattern. Real free gaps,
  but not tracking data — deferred to the free-factors phase, each gated by
  the backtest bar.

## Harness status

No pricing factor was introduced in this phase (sources are acquisition-only),
so there is no candidate to gate. The backtest suite was run green from
`~/workspace/sportsedge-backtest` as the no-regression check. When a factor is
proposed (free-factors phase), it must earn PASS vs the existing model and the
market baseline; note the harness settles ML/SPREAD/TOTAL only — player-prop
settlement (the natural consumer of tracking data) is not yet implemented,
which bounds what can be validated today.

## DK market-coverage matrix

No action needed: both wired sources are *feature* sources for existing markets
(MLB pitcher props / NFL player props), not newly enabled markets, and none of
the NOT_WIRED findings newly rule out a market from the matrix.
