# Market provider migration ledger — 2026-09-15

Status: routing/provenance work only. This document grants no Model_P, promotion, Truth Gate, staking, eligibility, or OFFICIAL authority.

## Non-silent-satisfaction invariant

A transport/source may satisfy only the market, book-identity, freshness, and evidence properties established by its own payload and contract. A fallback never inherits the primary source's identity. Missing market coverage stays missing.

## ESPN book-identity finding

The current `sportsedge/espn_game_odds_source.py` does not hard-code DraftKings. It reads `competition.odds[].provider.displayName` from the ESPN payload and writes that value to `sportsbook`; `book_key` is normalized from the same payload value. If the payload says `DraftKings`, that observation has ESPN transport plus source-attributed DraftKings book identity. If the provider field is absent/unusable, the adapter falls back to `ESPN partner` / `espn_partner`, which MUST NOT satisfy an exact-DraftKings contract.

This distinction supersedes the older shorthand label `ESPN_WEB_HEADER_DRAFTKINGS`: transport provenance is `ESPN_SCOREBOARD`; book identity is a separate source-payload assertion.

## Freshness

For free ESPN game odds, source-native update time is mandatory. Routing TTL is declared as 60 seconds in `config/market_provider_contract_v1.json`. This is a source-routing property, not a replay/evidence-policy TTL. Missing, future, or stale source timestamps fail closed.

## Consumer migration ledger

| Consumer / lane | Previous/primary source | Free source / routing | Provenance label | Markets | Exact book proof | Evidence/confirmation authority |
|---|---|---|---|---|---|---|
| MLB automatic / RUN IT full-game prices | The Odds API | ESPN scoreboard eligible as free game-market route/fallback | `ESPN_SCOREBOARD` + payload `sportsbook` | ML, RL, totals | Only when ESPN payload `provider.displayName` explicitly names required book | No inherited authority; contract-specific admission still required |
| MLB automatic props / NRFI-YRFI / team totals / additional derivatives | The Odds API | No ESPN substitution | `THE_ODDS_API` when acquired | props, NRFI/YRFI, team totals, derivatives | Provider/bookmaker payload | Unchanged; missing source remains fail-closed |
| NFL 2026 frozen confirmation | The Odds API / frozen DraftKings contract | NO MIGRATION IN THIS CHANGE | existing frozen provenance | frozen confirmation markets | Frozen contract controls | UNCHANGED; frozen script/config/workflow excluded |
| Schedule / due-window discovery | nflverse / official sport schedule sources as already implemented | unchanged free source | source-specific | schedule only | N/A | Cannot satisfy sportsbook evidence |
| Historical NFL modeling | nflverse | unchanged free source | `NFLVERSE` | historical game/model inputs | N/A | Modeling provenance only, not live sportsbook evidence |

## Spend audit status

No claim is made yet about which lane exhausted the monthly quota. The NFL confirmation workflow is schedule-gated before capture and its outside-window provider preflight is throttled. MLB forward designs also contain schedule/window gating. Historical paid recovery is a plausible consumer, but remains an inference until durable request/quota ledgers or workflow evidence establish consumption. Migration savings therefore MUST NOT be estimated from the exhaustion event alone.

## Frozen exclusion

This branch must not modify:
- `scripts/nfl_2026_line_capture.py`
- `config/nfl_2026_capture.json`
- `.github/workflows/nfl-2026-line-capture.yml`

Those files participate in the frozen NFL confirmation contract.
