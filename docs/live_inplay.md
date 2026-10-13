# Live / In-Game Research Repricing (Phase 6)

Branch: `feat/live-inplay-20261011`. Status: **IN_BUILD** for MLB/NFL/CFB.

Flow: Isaac sends live lines (same intake shape as `artifacts/run_it_full.py`),
gets a research card back. **Research-only**: no auto-betting, no bet
execution, no bet-placement code paths anywhere in the live path
(`sportsedge/live_run_it.py` asserts this in tests).

## Architecture

```
Isaac's live lines (phone intake, same shape as run_it_full)
        |
        v
sportsedge/live_run_it.py        -- phone-shaped runner, research card
        |-- sportsedge/live_poll.py        -- poll-based ingestion (free only)
        |-- sportsedge/live_state.py       -- game-state model + staleness
        |-- sportsedge/live_participation.py -- in-game participation gate
        |-- sportsedge/live_reprice.py     -- state -> P(ML/SPREAD/TOTAL)
        |-- artifacts/free_models.score_means -- pregame means (shared)
```

The pregame score means are reconstructed with the pregame context clock
pinned to kickoff-5min (`live_run_it._pregame_means`), so no post-kickoff
information can leak into them. They inherit whatever participation
adjustments `free_models.context_for`/`score_means` carry, including the
in-progress injury/QB hotfix (2026-10-11). The live path calls the same
`score_means` function the pregame runner uses -- a single source of truth
(extracted from `calculate()` in this branch; pregame tests still pass).

## Free sources only

| Sport | State source | Participation source |
|---|---|---|
| MLB | StatsAPI live feed `api/v1.1/game/{gamePk}/feed/live` | Same feed: current pitcher/batter every pitch + `gameData.probablePitchers` |
| NFL | ESPN scoreboard `competitions[].situation` + `status` | ESPN summary `injuries` section (per-team, timestamped) |
| CFB | ESPN scoreboard (same) | **NOT_WIRED** -- CFB summaries carry no injuries section on the free endpoint |

No paid feeds, no scraping behind logins. Isaac's supplied live line/price
is used ONLY for downstream EV comparison, never as a model input
(LIVE_POLICY_V1 forbidden features: `live_odds`, `live_line`, `live_price`,
...). The live repricing is market-blind by construction.

## Poll cadence and rate limits (`sportsedge/live_poll.py`)

- `LIVE_POLL_CADENCE_SECONDS = 30` per live event per provider.
- `LIVE_MAX_REQUESTS_PER_MINUTE = 40` per provider (conservative vs. the
  public endpoints; research polling must not look like abuse).
- `LIVE_REQUEST_SPACING_SECONDS = 0.25` between sequential requests.
- HTTP 429 is a **hard stop** for that provider in the current task
  (`LiveRateLimited`, no retry). Once a 429 is hit, the card halts further
  provider calls and remaining rows block with `LIVE_PROVIDER_RATE_LIMITED`.
- Typical use is one poll per research-card request; `LivePoller.poll_due`
  supports unattended loops at the 30s cadence.
- Every fetch emits a provenance receipt (URL, retrieved_at_utc,
  source_as_of_utc, status) attached to the card row.

## Staleness: hard fail-closed at 60s

`LIVE_STATE_STALENESS_THRESHOLD_SECONDS = 60` (Isaac's band: 60-90s).

Rationale: one poll cycle is 30s, so 60s tolerates exactly one missed
provider refresh before failing closed, while keeping in-game cards
actionable. Two independent clocks are checked (`staleness_reason`):
our retrieval time AND the provider's own timestamp (`metaData.timeStamp`
for StatsAPI, `status.type.lastUpdated` for ESPN). A provider serving a
cached/old snapshot is `STALE_LIVE_DATA` even if we just fetched it.
Stale -> no price, never guessed or extrapolated.

This is separate from the frozen `LIVE_POLICY_V1` TTLs (30s state / 20s
quote), which govern the bet-decision path (`sportsedge.live_engine`);
the research repricing path does not invoke that path.

## State model (`sportsedge/live_state.py`)

- MLB: score, inning, half, outs, balls, strikes, bases (display-only),
  current batter/pitcher ids+names, probable pitchers, kickoff, status.
- NFL/CFB: quarter, clock (seconds remaining + display), down, distance,
  yard line (raw; normalized 0-100 only when confidently parseable, else
  refused -- no guessing), possession (HOME/AWAY from team-id match),
  timeouts, score, kickoff, status.

Fields parsed for display but NOT priced carry explicit NOT_WIRED reasons
(see `NOT_WIRED_LIVE_FIELDS` in `live_reprice.py`): MLB bases/outs/count and
batter/pitcher identities; NFL/CFB down/distance/yard line/possession/
timeouts; live first-inning derivatives (deferred to Phase 1).

## Repricing math (`sportsedge/live_reprice.py`)

GAME markets first: ML / SPREAD / TOTAL.

- **MLB**: remaining runs per team ~ independent Poisson with the pregame
  mean scaled by that team's fraction of batting outs remaining
  (`mlb_outs_used`). Final = current score + remaining draws; ML ties split
  0.5/0.5 (same stated approximation as pregame). Extras: each team is
  granted one additional half-inning at its per-out pregame rate,
  re-evaluated every half-inning (stated assumption).
- **NFL/CFB**: the pregame Normal margin/total process with means scaled by
  the fraction of regulation time remaining and sds scaled by sqrt(f).
  **At f=1 (kickoff) the live repricing is exactly the pregame model**
  (unit-tested invariant across ML/SPREAD/TOTAL x sides x lines).
- **Overtime is blocked** (`LIVE_OT_DYNAMICS_UNMODELED`): sudden-death /
  alternating-possession dynamics are not modeled, and a degenerate
  zero-time model would emit false certainties.
- Only `LIVE` status is priced; FINAL/PREGAME/SUSPENDED/UNKNOWN block.

## In-game participation gate (`sportsedge/live_participation.py`)

Lesson of 2026-10-11 (Ravens 1H ML priced as if Lamar Jackson played;
Huntley started; MLB cards pitcher-blind -- all withdrawn): missing key
matchup input = blocked/downgraded, never silently priced. Applied in-game:

- **NFL (required check)**: the ESPN summary injury feed is parsed
  (per-team, timestamped entries). A **QB with status Out and a timestamp
  after kickoff** -> `LIVE_PARTICIPATION_CHANGE_UNPRICED`: refuse the price.
  Other post-kickoff "Out" entries -> warnings on the row (stated scoping:
  QB is the modeled key participant for football team strength; finer
  participation-impact modeling is queued behind the harness).
  If the summary source is unavailable or has no injuries section ->
  `LIVE_PARTICIPATION_UNVERIFIED`: refuse (a missing verification source
  is a reason code, not a guess).
- **MLB (diagnostic)**: probable-vs-current pitcher compared from the feed.
  Changes are routine (starters always exit); reliever impact is NOT_WIRED.
  An early pull (before the 4th) is flagged as a warning.
- **CFB (NOT_WIRED)**: no free in-game participation source exists.
  Priced with the explicit, audited assumption
  `PARTICIPATION_ASSUMED_UNCHANGED_SINCE_KICKOFF`
  (factor status `ASSUMED_NOT_VERIFIED`, never silent).
- Pregame participation (inactives known before kickoff) is handled by the
  pregame-means reconstruction (injury_points + the hotfix), not here.
- User-submitted participation flags are never accepted (untrusted intake).

Every priced row carries a `participation` factor in its factor-coverage
audit.

## Per-market classification (Live/In-Game)

| Market | MLB | NFL | CFB | Reason / note |
|---|---|---|---|---|
| ML | IN_BUILD | IN_BUILD | IN_BUILD | This phase; MLB in harness replay |
| SPREAD | IN_BUILD | IN_BUILD | IN_BUILD | Same machinery as ML |
| TOTAL | IN_BUILD | IN_BUILD | IN_BUILD | Same machinery as ML |
| TEAM_TOTAL | IN_BUILD | IN_BUILD | IN_BUILD | Falls out of the same distributions; not yet validated |
| 1H/2H/QTR ML/SPREAD/TOTAL | BLOCKED | BLOCKED | BLOCKED | `LIVE_SPLIT_UNMODELED`: no validated within-game split model |
| F5 (MLB) / inning markets | BLOCKED | n/a | n/a | `LIVE_SPLIT_UNMODELED` |
| NRFI/YRFI + live 1st-inning derivatives | BLOCKED | n/a | n/a | `LIVE_FIRST_INNING_DEFERRED`: waits on Phase 1 core first-inning work (`feat/mlb-first-inning-20261011`); not duplicated |
| ALT_SPREAD / ALT_TOTAL / ALT_RUN_LINE | NOT_WIRED | NOT_WIRED | NOT_WIRED | Priceable by the same machinery; not wired until primary lines validate |
| PITCHER_PROP (live) | NOT_WIRED | n/a | n/a | `LIVE_PITCHER_PROP_NOT_WIRED`: needs verified pitch-count/bullpen state model |
| BATTER_PROP (live) | NOT_WIRED | n/a | n/a | `LIVE_BATTER_PROP_NOT_WIRED`: needs verified remaining-PA model |
| PLAYER_PROP (live) | n/a | NOT_WIRED | NOT_WIRED | `LIVE_PLAYER_PROP_NOT_WIRED`: needs verified within-game stat projection |
| Futures / SGPs | NOT_WIRED | NOT_WIRED | NOT_WIRED | Out of scope for live (unchanged) |

Live/In-Game remains **IN_BUILD** (Phase 6) for MLB/NFL/CFB per
`market_coverage_dk.md`.

## Validation

- **MLB live ML repricing: CONDITIONAL_PASS in the harness replay**
  (45 completed 2025 games, 810 tick-by-tick predictions at half-inning
  boundaries from archived StatsAPI play-by-play; ticks stop at
  baseball-rules finality). Candidate (live-updated) vs existing (static
  pregame, same means estimator -- isolates the live-update factor):
  Brier 0.1627 vs 0.2338 (delta -0.0711), log-loss 0.4847 vs 0.6595
  (delta -0.1749), n=810. Calibration bins monotone and roughly aligned
  (see `data/live_validation_report.json`). Market-baseline leg MISSING
  (no archived prices for these games) -- hence conditional, not a full
  pass; do not promote on this verdict alone. Re-running with archived
  closing prices as the baseline (now authorized: Odds API keys are
  Actions-side, evaluation-only) is a queued follow-up.
  Run: `scripts/validate_live_mlb_replay.py` with cwd
  `~/workspace/sportsedge-backtest`.
- **NFL/CFB live repricing: CANNOT be validated yet.** ESPN does not retain
  completed-game live situation, so tick-by-tick replay is impossible from
  free sources. Blocked pending a free historical play-by-play source
  (nflverse is a candidate for the tracking-data phase). Unit-tested only:
  f=1 == pregame invariant, monotonicity in score/clock, OT block,
  fail-closed paths, participation gating.
- Spread/total share the ML machinery; the replay validates ML (plus TOTAL
  at the pregame total line -- see script).

## Known limitations

1. NFL/CFB live repricing is unvalidated (no archived in-game state).
2. Down/distance/yard line/possession/timeouts are parsed and shown but do
   not affect prices (no validated EP model).
3. MLB bases/outs/count and batter/pitcher identities are display-only.
4. CFB in-game participation cannot be verified on any free source
   (assumption-flagged, not silent).
5. Overtime is refused, not priced.
6. The replay's pregame means use a simple prior-games estimator, not the
   full pregame context stack (the comparison isolates the live factor).
7. Nothing here is a verified edge: statuses are
   `LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED` / `LIVE_BELOW_THRESHOLD`;
   `model_validation: NOT_PROVEN_VS_CLOSE` on every row.

## CLI

```
python3 artifacts/run_it_live.py --lines lines.json [--output card.json] [--min-ev 0.02]
```

Line shape: `{"sport","market","side","line","odds","game_pk"|"event_id"|"game"|"away"/"home","date"}`.
