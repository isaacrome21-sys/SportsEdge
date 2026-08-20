# SportsEdge NFL + CFB Full Market Specification Index

This is the implementation index for the football market-surface expansion.

## Source of truth

- `config/football_market_surface.json` — declared NFL/CFB market surface and independent state layers.
- `docs/football/FULL_MODEL_ORCHESTRATOR_SPEC.md` — shared A/B/C simulator contract, decision order, state grid, key numbers, CFB mismatch handling, correlation clusters, dependency graph, build order and edge-likelihood ranking.

## Per-market 7-section specs

- `docs/football/GAME_MARKET_SPECS.md` — moneyline, spread, total, team total, 1H, 2H, quarters, alternates and race-to-N.
- `docs/football/TEAM_SITUATIONAL_MARKET_SPECS.md` — first score, largest lead, margin bands, both teams to N, total TDs, longest FG, DST TD and safety.
- `docs/football/QB_MARKET_SPECS.md` — pass yards/completions/attempts/TDs/INTs, QB rush, longest completion, pass+rush.
- `docs/football/SKILL_MARKET_SPECS.md` — rush/receiving yards, receptions, rush attempts, targets, combos, longest plays, anytime/first/2+ TD.
- `docs/football/KICKER_DEFENSE_MARKET_SPECS.md` — FG made, kicking points, XP, player sacks, tackles+assists, player INT, team sacks and team turnovers.

Each market spec contains exactly the required sections: READ-OUT DEFINITION, REQUIRED INPUTS, HOLD AND THRESHOLD, SETTLEMENT RULES, VALIDATION PLAN, STATE TRANSITIONS, CORRELATION CLUSTER.

## Positional matchup / usage feature layer

`sportsedge/core/position_matchup.py` now builds defensive WR/TE/RB target-share-over-expected, continuity-adjusts it for defensive playcaller/personnel change, and optionally crosses it with offensive positional target share. NFL and CFB M2 import the same market-blind helper. The interaction features are:

- `wr_usage_x_opp_target_oe`
- `te_usage_x_opp_target_oe`
- `rb_usage_x_opp_target_oe`
- `positional_target_matchup_pressure`

The interaction is only emitted when an offense positional usage map is present. Team/game M2 can degrade without it; player-prop Engine B still blocks when player participation/usage is unresolved.

## Contract tests

- `tests/test_football_position_matchup.py`
- `tests/test_football_market_surface.py`

These enforce the target-OE/usage math, defensive continuity discount, NFL/CFB M2 integration, full declared market coverage, A/B/C dependencies, and the rule that PASS is not a run/engine state.
