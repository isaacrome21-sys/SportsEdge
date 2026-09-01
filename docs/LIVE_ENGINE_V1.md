# LIVE_ENGINE_V1

Status: **SHADOW / UNVALIDATED**

LIVE_ENGINE_V1 adds a shared real-time decision layer for MLB, NFL, and CFB without changing the semantics of the existing pregame governed model or downstream RUN IT context layer.

## Governed live path

`PREGAME PRIOR -> LIVE EVENT DISCOVERY -> PIT LIVE STATE -> LIVE_PIT_CUTOFF -> SPORT ADAPTER -> LIVE Model_P -> PAIRED LIVE QUOTE -> NO-VIG MARKET_P -> EDGE -> EV -> KELLY/EXPOSURE -> LIVE TRUTH GATE`

The engine never creates Model_P from betting splits, public money, social sentiment, line movement, sportsbook prices, or handicapper opinion. Those remain downstream context or market-comparison evidence only.

## RUN IT routing

One RUN IT command is slate-aware:

- `PREGAME` events route to the existing pregame lane.
- `LIVE` events route automatically to LIVE acquisition and live-engine evaluation.
- `FINAL` events are settlement-only and cannot produce a new bet.
- `SUSPENDED` events are blocked.

Live event discovery/state acquisition currently has an ESPN scoreboard provider. Main-market live quotes have a The Odds API provider when a valid key is configured. Missing automatic data is reported as an exact `DATA_GAP`; it is never estimated or silently substituted. A user-supplied screenshot/manual quote can fill only the exact missing market through the same normalized quote schema.

## LIVE_PIT_CUTOFF

Live PIT is evaluated continuously, not once per matchup. Every decision snapshot is frozen at an exact point-in-time cutoff. A feature with an as-of timestamp after that cutoff is ineligible for the prediction. A later play, score, pitch, injury, substitution, drive result, or other event may not leak backward into an earlier snapshot.

Every normalized live snapshot records event ID, sport, source as-of time, retrieval time, PIT cutoff, state sequence, provider, policy version, raw state, and governed model features. Its immutable `snapshot_id` is a deterministic hash of those inputs so MANUAL/HYBRID/AUTO replay can prove identity.

## Market blindness

LIVE Model_P is explicitly market-blind under `LIVE_POLICY_V1`. Forbidden predictive inputs include live odds, live line/price, no-vig market probability, line movement, steam, tickets, money/handle, public/consensus percentages, sportsbook-derived projections, handicapper picks, and social sentiment.

The live market is used only after Model_P as the comparator for paired no-vig probability, edge, EV, Kelly/exposure, and downstream LIVE CONTEXT. This separation is required even when the market reprices immediately after a play.

## Shared fail-closed rules

A governed live decision is BLOCKED when any required condition is missing or stale, including:

- no live Model_P
- model not deployed
- model not validated
- stale game state
- stale paired quote
- inactive market
- invalid/future timestamps
- missing required sport-specific state
- LIVE_PIT_CUTOFF violation
- forbidden market-derived model feature
- frozen live TTL policy mismatch

A paired quote is mandatory for two-way no-vig probability. One-sided odds cannot be silently substituted. Three-way contracts are not silently collapsed into two-way markets; a governed three-way price requires all outcomes and a separately supported no-vig contract.

## Frozen LIVE TTL policy

`LIVE_POLICY_V1` freezes state freshness at **30 seconds** and paired quote freshness at **20 seconds**. These are current operational governance values, not claims that those values are economically optimal. Changing them requires a new policy version and new validation evidence; callers cannot silently widen or tighten them inside V1.

## Automatic market scope

The registry covers main and derivative live markets across NFL, CFB, and MLB, including moneyline, spread/run line, totals, team totals, halves/quarters/innings where applicable, NRFI/YRFI, alternate lines, batter props, pitcher props, and player props.

Provider coverage and model eligibility are separate concepts. A market may be in scope while a particular provider cannot retrieve it. That is a market-specific `DATA_GAP`, not permission to infer a price and not a reason to block unrelated markets. One-sided props may be analyzed as downstream context, but they cannot pass the governed no-vig path without a valid opposing price or separately validated multi-outcome pricing contract.

## NFL live adapter

Required state includes score, quarter/clock, possession when known, down, distance, field position, timeouts, and play counts. Future model versions may add EPA/play, success rate, explosive rate, pressure, drive quality, pregame team/QB priors, weather, and injury state, but those fields must be point-in-time safe before becoming governed features.

## CFB live adapter

Uses the football state contract plus point-in-time pregame team ratings. CFB-specific future governed features may include QB prior, roster/talent prior, opponent-adjusted efficiency, drive efficiency, field-position state, and pace. Public betting context remains excluded from Model_P.

## MLB live adapter

Required state includes inning/half, outs, count, occupied bases, batting team, score, and pregame team ratings. Future governed features may add pitcher/batter identities, pitch count, times-through-order, bullpen availability, lineup state, handedness, Statcast inputs, park/roof/weather, and leverage state when point-in-time safe.

## Validation and promotion

The code being present does **not** make a live model validated. Each sport/market must remain SHADOW until forward/out-of-sample evidence satisfies a separately frozen live promotion policy.

Within-game snapshots are correlated and cannot be counted as independent observations. Holdouts, bootstrap/confidence intervals, CLV inference, ROI inference, and promotion sample-size evidence must cluster at the `event_id`/game level. Raw snapshot count is logged separately from independent game-cluster count.

At minimum, the evidence package should measure calibration, Brier/log loss versus a contemporaneous no-vig live-market baseline, CLV, post-vig ROI, edge-bin monotonicity, freshness failures, game-clustered uncertainty, and mode parity. Historical replay must respect real state timestamps, quote timestamps, suspension windows, and availability; a quote that was not available at the decision timestamp cannot be used retrospectively.

Until promotion, valid engine executions with an unvalidated model return `BLOCKED: LIVE_MODEL_NOT_VALIDATED`.

## Execution-mode parity

MANUAL, HYBRID, and AUTO may differ in acquisition mechanism, not semantics. Given the same normalized live snapshot, live model output, paired quote, and policy config, all modes must produce identical no-vig probability, edge, EV, Kelly, block/pass/bet status, and reason code. Any difference on identical normalized inputs is a parity failure.
