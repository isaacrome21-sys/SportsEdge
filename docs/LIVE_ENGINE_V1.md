# LIVE_ENGINE_V1

Status: **SHADOW / UNVALIDATED**

LIVE_ENGINE_V1 adds a shared real-time decision layer for MLB, NFL, and CFB without changing the semantics of the existing pregame governed model or downstream RUN IT context layer.

## Governed live path

`PREGAME PRIOR -> PIT LIVE STATE -> SPORT ADAPTER -> LIVE Model_P -> PAIRED LIVE QUOTE -> NO-VIG MARKET_P -> EDGE -> EV -> KELLY/EXPOSURE -> LIVE TRUTH GATE`

The engine never creates Model_P from betting splits, public money, social sentiment, line movement, or handicapper opinion. Those remain downstream context only.

## Shared fail-closed rules

A live decision is BLOCKED when any required condition is missing or stale, including:

- no live Model_P
- model not deployed
- model not validated
- stale game state
- stale paired quote
- inactive market
- invalid/future timestamps
- missing required sport-specific state

A paired quote is mandatory for no-vig probability. One-sided odds cannot be silently substituted.

Default runtime freshness budgets in V1 are 30 seconds for game state and 20 seconds for the live quote. They are operational defaults, not empirically validated edge thresholds, and may be tightened by the caller.

## NFL live adapter

Required state includes score, quarter/clock, possession when known, down, distance, field position, timeouts, and play counts. Future model versions may add EPA/play, success rate, explosive rate, pressure, drive quality, pregame team/QB priors, weather, and injury state, but those fields must be point-in-time safe before becoming governed features.

## CFB live adapter

Uses the football state contract plus point-in-time pregame team ratings. CFB-specific future governed features may include QB prior, roster/talent prior, opponent-adjusted efficiency, drive efficiency, field-position state, and pace. Public betting context remains excluded from Model_P.

## MLB live adapter

Required state includes inning/half, outs, count, occupied bases, batting team, score, and pregame team ratings. Future governed features may add pitcher/batter identities, pitch count, times-through-order, bullpen availability, lineup state, handedness, Statcast inputs, park/roof/weather, and leverage state when point-in-time safe.

## Validation and promotion

The code being present does **not** make a live model validated. Each sport/market must remain SHADOW until forward/out-of-sample evidence satisfies a separately frozen live promotion policy. At minimum, the evidence package should measure calibration, Brier/log loss versus a no-vig live-market baseline, CLV, post-vig ROI, edge-bin monotonicity, freshness failures, and mode parity.

Until promotion, valid engine executions with an unvalidated model return `BLOCKED: LIVE_MODEL_NOT_VALIDATED`.

## Execution-mode parity

MANUAL, HYBRID, and AUTO may differ in acquisition mechanism, not semantics. Given the same normalized live state, live model output, paired quote, and policy config, all modes must produce identical no-vig probability, edge, EV, Kelly, block/pass/bet status, and reason code. Any difference on identical normalized inputs is a parity failure.
