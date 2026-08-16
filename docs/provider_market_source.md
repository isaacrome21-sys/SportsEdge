# Provider market source contract

The live MLB quote adapter uses The Odds API event-odds endpoint for additional/player markets and the featured odds endpoint for full-game moneyline/run-line/totals. Market keys are normalized to SportsEdge canonical names before any downstream decision logic.

Provider market availability is not assumed. Missing bookmaker markets remain explicit acquisition gaps, not synthetic quotes. The event-markets endpoint may be used to discover currently opened markets close to game time without changing canonical SportsEdge semantics.
