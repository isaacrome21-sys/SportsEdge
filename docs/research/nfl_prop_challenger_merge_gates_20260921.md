# NFL prop challenger merge gates — 2026-09-21

Research-only contract. Nothing here creates Model_P, Truth Gate, promotion, staking, backfill, or OFFICIAL authority.

## Separate lane

The prop challenger uses `SPORTSEDGE_NFL_PROP_RESEARCH_CARD_V1` and `SPORTSEDGE_NFL_PROP_RESEARCH_LEDGER_V1`, with ledger namespace `ledger/nfl_prop_research`. It does not render through the NFL game-market card schema from #896.

## Correlation / independence

Every prop row carries:
- a component group (`USAGE`, `YARDAGE`, `TD`, or `TURNOVER`);
- `component_group_id = <player>:<component>`;
- `correlation_group_id = PLAYER:<player>`;
- `independence_unit_id = PLAYER:<player>`.

Multiple edges from one player remain visible but count as one independent play. This prevents rushing yards, receiving yards, TDs, and other same-player outputs from inflating an independent-play denominator merely because they came from separate market rows.

## Point-in-time role projection

The supported card/ledger entry path requires a decision `as_of`, current game identity, a pregame projected-role retrieval timestamp, and strictly prior history timestamps/game IDs. A history row from the current game is rejected even if supplied. A regression test explicitly supplies realized same-game snaps and requires failure.

## Frozen context multipliers

Context coefficients and thresholds live in `config/research/nfl_prop_challenger_context_v1.json`. The wrapper returns the policy ID and SHA-256 of the exact policy bytes with each adjusted role projection. Any coefficient, threshold, input definition, or bound change requires a new policy version/ID and hash before evaluation. V1 coefficients remain unvalidated challenger settings and cannot be tuned after observing prop results under the same version.

Authority footer: `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`.
