# NFL direct DraftKings confirmation source contract v1

`DRAFTKINGS_DIRECT_WEB_V1` is the primary prospective transport for the frozen NFL confirmation lane.

It preserves raw DraftKings response bytes and SHA-256 and uses the SportsEdge HTTP response receipt time as the observation-time upper bound. Provider quote timestamps are auxiliary only and are never synthesized.

Fallback to `DRAFTKINGS_ODDS_API_V1` is allowed only after whole-source direct transport/identity failure. A valid direct board with a missing, one-sided, or otherwise unadmitted market does not trigger fallback, and markets from different sources are never combined into one capture.

Every admitted spread and total must be exact and two-sided. Schedule identity must match the independent NFL schedule by exact kickoff-UTC multiplicity before a capture can bind.

This contract is prospective only. It permits no backfill and cannot rewrite prior misses or existing confirmation records. It grants no Model_P, Truth Gate, promotion, deployment, staking, or OFFICIAL authority.
