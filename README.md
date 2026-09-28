# SportsEdge

SportsEdge is a research and evidence-collection system for sports probabilities.
No code merge by itself grants Truth Gate, OFFICIAL, or staking authority.

## Current work

- NFL: frozen attempt-9 decision/evidence contracts and evaluator; week-cluster inference is separately policy-bound. Real decision capture and settlement still require operational verification.
- MLB: full-game moneyline/run-line/total research and PIT capture; other market families need their own evidence.
- NBA/NHL: simulation and feature modules exist. Fitted artifacts, PIT feeds, forward price pairing and market-level validation remain separate gates.
- CFB: paused research; candidate and data-source branches are parked, not discarded.

See [the dated finish audit](docs/FINISH_STATUS_2026-09-28.md) for verified commits, missing evidence and next actions. [Live promotion status](docs/LIVE_PROMOTION_STATUS.md) describes the separate in-game lane.

## HYBRID from a phone

Send fresh screenshots or a transcription of both sides of each market, including the sportsbook, exact line, prices and capture time with timezone. Include the game and start time. An operator must bind those quotes to independent estimates or joint-score simulations before a card can run. Screenshots, market consensus and confidence scores do not create Model_P.

NFL command and input contract: [NFL RUN IT](docs/NFL_RUN_IT_CARD.md).
MLB intake and pregame requirements: [MLB RUN IT](docs/MLB_RUN_IT_PREGAME.md).

A missing opposite price, stale quote, absent model input or unvalidated market can produce an empty card. Research cards retain `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.

## Development

Use the versions pinned in `.python-version` and the requirements files. Fetch full Git history for provenance tests. Run focused tests for the changed subsystem before opening a PR. Main requires the real reconciliation hold and CFB readiness checks; do not bypass them.
