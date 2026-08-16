# SportsEdge Full-System Audit Handoff — 2026-08-11

## Purpose
This document is an independent-audit handoff for the entire SportsEdge MLB automation stack. The auditor should assume nothing stated in chat is true unless reproduced from repository code, checked-in evidence, CI logs, or live provider responses.

## Required end state
A single Full Model invocation must account for every required market family and produce one evidence bundle containing source freshness, identity binding, lineup/starter state, feature provenance, model probability, sportsbook probability, edge/EV, gate decision, and reason codes. A market may be ACTIONABLE, PASS/NO_BET, BLOCKED, ACQUIRED_NO_MODEL, or NOT_FOUND. It may not silently disappear.

Required families:
- Moneyline
- Run line
- Full-game totals
- F5 moneyline
- F5 run line
- F5 totals
- NRFI/YRFI
- Pitcher strikeouts
- Pitcher outs
- Pitcher hits allowed
- Pitcher walks
- Pitcher earned runs
- Batter hits
- Batter total bases
- Batter RBI
- Batter runs

## Current repository truth to verify
1. `main` contains native official-MLB history reconstruction for HITS and TOTAL_BASES and ordered Odds API failover.
2. This audit branch adds native DraftKings game-line acquisition for h2h/spreads/totals in `sportsedge/game_odds_source.py`.
3. This audit branch adds explicit game-market validation policy in `sportsedge/game_market_contract.py`.
4. This audit branch passes four configured Odds API secrets into the scheduled runner and CLI instead of three.
5. This audit branch preserves safe Odds API HTTP/network failure identity without logging request URLs or API keys.
6. This audit branch requests the documented MLB pitcher markets `pitcher_strikeouts`, `pitcher_outs`, and `pitcher_hits_allowed` in addition to the existing hitter and walk markets. Acquisition is not equivalent to model deployment.

## Validation boundaries — do not loosen during audit
Recovered legacy validation evidence says:
- Moneyline: beta/eligible, but deployment parity must be proven before release.
- F5 ML/RL/totals: gated/eligible in legacy evidence; current live wiring still must be proven.
- NRFI/YRFI: gated/eligible in legacy evidence; current live wiring still must be proven.
- Pitcher strikeouts: eligible in legacy evidence.
- Pitcher outs: eligible in legacy evidence.
- Pitcher hits allowed: eligible in legacy evidence.
- Pitcher walks: blocked by failed direct holdout until an identical online recalibration state is deployed and reproduced.
- Pitcher earned runs: blocked by failed direct holdout/deployment parity.
- Full-game run line: blocked until deployed run-distribution parity is independently proven.
- Full-game totals: blocked until fresh independent distribution calibration is proven.

Do not infer that market acquisition or existence of an old engine makes a market official-eligible.

## High-priority defects observed in live operation
### A. Prop acquisition failure was opaque
A live workflow successfully acquired game markets but the prop path returned zero quotes with per-event fetch failures. Previous diagnostics collapsed the root cause into `ODDS_API_FETCH_FAILED`. Audit the new safe HTTP status/provider error-code preservation and reproduce at least one invalid-key, quota/error, and invalid-market case without leaking keys.

### B. Only a subset of configured Odds API keys was exposed in some workflows
Verify every production/scheduled/manual runner uses all intended key slots in deterministic order, deduplicates identical values, never logs a secret, and fails closed only after all unique keys fail.

### C. Game-market acquisition and model pricing are separate
`game_odds_source.py` is price acquisition only. Verify sportsbook implied probability is never used as `Model_P`. No ML/RL/total should be called an official SportsEdge play until an independent model path produces Model_P and the market's validation policy allows it.

### D. Event binding noise / out-of-slate provider events
Provider event IDs are not trusted. Events bind by normalized exact home/away identity plus start-time tolerance to one MLB StatsAPI game. Audit doubleheaders, postponed/rescheduled games, neutral-site games, renamed teams, and provider events outside the Chicago slate date. Unmatched or ambiguous events must not be guessed.

### E. Player identity and lineup binding
Player names from sportsbooks are not trusted as identity. Verify exact game-scoped mapping to MLB player IDs, confirmed/projected lineup state, probable/confirmed starter identity, doubleheader game number, and pregame cutoff. Ambiguous names must fail closed.

### F. Market coverage must be explicit
Audit output must list every required market family every run. Missing market families must show a reason such as NOT_FOUND, ACQUISITION_FAILED, MODEL_NOT_WIRED, VALIDATION_BLOCKED, LINEUP_UNCONFIRMED, PRICE_STALE, GAME_NOT_PREGAME, or FEATURE_MISSING. Silent omission is a failure.

## Source/provenance rules
- Sportsbook data supplies only price/line/book/offer identity and retrieval timestamp.
- Official MLB data may supply schedule, game identity, player/team IDs, starter status, confirmed lineup/boxscore structure, venue identity, and historical game logs used by validated feature contracts.
- Projected lineups must carry their own retrieval timestamp and TTL and must not be represented as confirmed.
- Weather/umpire data, when added, must be structurally separate provenance with source, event time, retrieval time, TTL, and exact game binding.
- Frozen training artifacts such as TB park factors must remain frozen unless a separately validated model explicitly uses live weather/park inputs.
- No BvP, hot streak, Statcast, public betting, weather, or sportsbook information may silently enter a model whose validated feature contract did not include it.

## Audit test plan
### 1. Repository integrity
- Record commit SHA and branch.
- Hash deployment registry, model artifacts, frozen park table, feature-engine files, and validation registry/evidence files.
- Confirm no untracked runtime dependency is required to reproduce local tests.

### 2. Unit/regression suite
Run the entire test suite, not only a curated subset. Then specifically run tests covering:
- quote identity and American-odds validity
- double-TTL freshness
- candidate binding
- pregame/game-state gate
- Odds API key failover and secret non-disclosure
- event binding/doubleheaders
- Hits full holdout
- Total Bases full holdout
- deployment/attestation registry
- native history cache corruption and date rollover
- game-market source and policy

### 3. Live source smoke test
For one current MLB slate:
- Fetch MLB schedule once.
- Fetch DraftKings h2h/spreads/totals and event-level markets.
- Record all provider error codes and key slots without secret values.
- Verify every emitted quote binds to one MLB game and, for player props, one MLB player.
- Verify no started game enters the pregame card.

### 4. Full market coverage test
Expected audit artifact should contain rows for every required family. For each family record:
`market_family, acquisition_state, model_state, validation_state, quote_count, candidate_count, official_bet_count, primary_block_reason`.
Any absent family is an audit failure.

### 5. Model_P independence test
For every official-eligible candidate, perturb sportsbook odds while holding model features fixed. `Model_P` must not change. Edge/EV may change. If Model_P changes, fail the audit.

### 6. Reproducibility
Repeat identical candidate/model inputs in a clean process with fixed seed/identity. Exact or documented-tolerance probabilities must reproduce. Tied candidate ordering must reproduce cross-process.

### 7. Holdout/deployment parity
For each market proposed for official release, require an independently reproduced holdout result using the exact production engine and feature contract. Old research code or an acceptance wrapper is not production parity.

### 8. Failure injection
Inject and verify fail-closed behavior for:
- all odds keys invalid/exhausted
- one bad key followed by one good key
- stale/future price timestamp
- missing TTL
- provider clock reversal
- ambiguous doubleheader
- unmatched venue
- projected lineup stale/incomplete
- confirmed starter changed
- player absent from game roster/lineup
- cache corruption
- missing model artifact
- validation registry malformed/missing

## Acceptance criteria for “fully functional”
Do not call SportsEdge fully functional until all of the following are true:
1. One command produces one evidence bundle without manual screenshots.
2. All required market families are explicitly accounted for.
3. All four intended Odds API key slots are usable by the production workflow.
4. Game and player binding passes live and regression tests.
5. HITS and TOTAL_BASES use the independently validated production feature contracts.
6. ML, F5, NRFI/YRFI, pitcher K/outs/hits have production inference paths whose parity is independently reproduced.
7. RL/full-game totals remain blocked unless their current production distributions earn fresh validation.
8. Pitcher walks/earned runs remain blocked unless new production-parity evidence supersedes the failed evidence.
9. Weather/umpire/projected-lineup integrations have explicit TTL/provenance and cannot silently alter a frozen feature contract.
10. Full test suite and live smoke test are green.
11. A legitimate no-play slate is allowed, but zero plays caused by infrastructure/plumbing must be distinguishable from a true model no-play slate.

## Auditor deliverables requested
Return:
- PASS/FAIL for each acceptance criterion above.
- Exact commit SHA tested.
- Full commands executed.
- Test counts and failures.
- Live-source request summary with secrets redacted.
- Market-coverage matrix.
- Any mismatch between legacy evidence and current production code.
- Any path where sportsbook probability can contaminate Model_P.
- Any stale/postgame/future-data path.
- Any silent default or fallback that can create an official bet.
- Final list of markets safe for official release vs blocked, with evidence references.

## Auditor prompt
Use the following instruction verbatim if handing the repository to another coding/review agent:

> Audit SportsEdge as an adversarial independent reviewer. Do not trust chat summaries, commit messages, prior PASS labels, or claimed CI results. Build and execute the repository yourself. Trace the live Full Model path from source acquisition through identity binding, feature provenance, production model inference, Monte Carlo, price freshness, EV/Kelly, deployment policy, Truth Gate, and final card. Require every requested MLB market family to be explicitly accounted for; silent omission is a failure. Prove Model_P is independent of sportsbook implied probability. Reproduce holdout/deployment parity for any market proposed as official. Inject stale prices, future timestamps, bad keys, ambiguous games/players, missing features, corrupted cache, and malformed registries and verify fail-closed behavior. Do not loosen gates to manufacture bets. Return a market-by-market PASS/BLOCKED matrix, exact commands/tests/results, commit SHA, hashes of critical artifacts, and every defect found with file/line references. Treat a legitimate zero-bet card as valid, but distinguish it from infrastructure-caused zero bets.
