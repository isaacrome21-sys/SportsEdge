# MLB V8 replay + forward evidence

## Frozen evidence boundary

V8 forward evidence begins **2026-09-03T00:00:00Z**. Pre-epoch rows are not V8. A T0/close row observed at or after first pitch is rejected rather than re-labeled as pregame.

Raw collection, normalization, calibration, and promotion are separate steps. Creating an archive never changes `eligible=false`, an edge floor, or any Truth Gate result.

## Replay source classes

| Source | What it can prove | Use |
|---|---|---|
| SportsEdge V8 forward | Exact timestamped first-party capture with source SHA | decision + close |
| The Odds API (`the-odds-api.com`) | Historical point-in-time snapshots; featured history and event-level additional markets | decision + close |
| TheOddsAPI (`theoddsapi.com`) | Timestamped archive beginning 2026-05-13 | secondary PIT rescue |
| OpticOdds | Timestamped price history, rolling two-month retention | July/August PIT rescue while retained |
| SportsDataIO | Timestamped betting line movement from open through close | PIT/line-movement rescue under license |
| SportsGameOdds | Bookmaker open/close fields on finalized events | close benchmark; not a fabricated T-90 decision |
| The Odds Gap | Per-scan game prices; recent/rolling export and early-August prop checkpoints | import-only rescue subject to its terms |
| MLB StatsAPI | schedule/game identity/final outcomes | outcome authority only |
| Baseball Savant | historical baseball/Statcast context | strictly-prior context replay only |

`SOURCE_REGISTRY` in `sportsedge/mlb_evidence_archive.py` is executable policy. Unregistered imports default to no calibration eligibility.

## 38-market mapping

`config/mlb_replay_source_map_v8.json` maps every canonical SportsEdge MLB market to documented provider market keys where a direct sportsbook market exists. Missing/composite markets remain missing. SportsEdge never manufactures a sportsbook quote by adding component props together.

`FIRST_HOME_RUN` remains an N-way benchmark problem. A two-sided devig must not validate it.

## CLV comparability

Moneyline decisions can pair to the same book/source close directly. Spread, total, team-total and player-prop decisions pair only when the close contains the **same original wager threshold**. A moved close line at another threshold is recorded but returns `NO_EXACT_THRESHOLD_CLOSE` for CLV.

## March-August replay execution

The replay workflow is deliberately manual for paid historical calls:

1. Run `mlb-v8-replay` with `execute=false` to produce a zero-credit plan.
2. Review `estimated_provider_credits`.
3. Re-run with `execute=true` and an explicit `max_estimated_credits` at least as large as the plan.
4. The workflow writes exact provider bytes, canonical JSONL, source hashes, schedule hash and a manifest, then persists the completed archive to the `data` branch.

The first pass requests `h2h,spreads,totals` at `T-90` and strictly-prestart close. Additional/player markets are event-level and substantially more expensive; their direct provider keys are frozen in the 38-market map for staged replay rather than silently skipped.

## September 3 forward collection

The existing lightweight archive scheduler remains the clock. From the V8 epoch it now:

- keeps multi-book featured snapshots at T-180/T-90/T0;
- canonicalizes only strictly pregame rows;
- records DraftKings/FanDuel/BetMGM/William Hill US plus Pinnacle when returned;
- at valid T0, captures documented additional/player/period markets once for close evidence rather than polling props all day;
- persists canonical market evidence to the `data` branch;
- persists every canonical AUTO card and immutable prediction journal to the `data` branch when the model runs;
- retains 90-day Actions artifacts as a second copy, not as the authoritative archive.

Missing source access, provider exhaustion, unmatched identity, poststart capture, unsupported market shape and missing exact-threshold close are evidence gaps, never synthetic observations.
