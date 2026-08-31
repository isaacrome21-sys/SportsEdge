# SportsEdge CFB model feature / PIT trace

Status: implementation trace only. This document is **not** predictive validation or promotion evidence.

## Canonical predictive path

`run_cfb_machine(...)` resolves MANUAL / HYBRID / AUTOMATIC ingress and converges on `_run_canonical(...)` in `sportsedge/sports/cfb/run_machine.py`. For supported full-game markets, `_run_canonical(...)` builds one market-blind game row and calls `simulate_cfb_joint_distribution(...)`. `price_cfb_game_markets(...)` applies sportsbook spread/total thresholds only after that distribution exists.

Current supported predictive readouts are exactly:

- full-game MONEYLINE
- full-game SPREAD
- full-game TOTAL

Teaser, parlay, SGP, live, first-half, team-total, and player-market labels do not have CFB engines and must remain `NO_ENGINE` / `BLOCKED` until independently implemented and validated.

## Actual model inputs

`CFB_JOINT_GAME_FEATURES_V1` consumes the following team metrics for both home and away teams:

- `off_ppa_rush`
- `off_ppa_dropback`
- `def_ppa_rush_allowed`
- `def_ppa_dropback_allowed`
- `off_success_rate`
- `def_success_rate_allowed`
- `standard_down_ppa`
- `passing_down_success_rate`
- `eckel_rate`
- `points_per_eckel`
- `points_per_drive`
- `net_field_position`
- `explosive_rate`

The model also derives matchup differences from those fields and consumes:

- home-field / neutral-site indicator
- indoor indicator
- wind speed
- temperature

The joint model fits home and away score means with ridge regression, then replays paired training residuals to preserve observed home/away residual dependence. Tied simulated regulation paths require an empirical overtime delta profile. The stochastic stream requires an explicit seed.

## Explicitly absent from the current feature contract

The following are **not** present in `CFB_JOINT_GAME_FEATURES_V1` and must not be described as modeled until code and PIT provenance exist:

- QB identity / QB-specific adjustment
- injuries or availability
- depth chart / roster availability
- recruiting/talent composite
- transfer-portal adjustments
- coach/coordinator continuity
- travel distance / timezone crossings
- rest / short week / bye effects
- explicit havoc/pressure/sack features
- special-teams efficiency
- tempo / seconds-per-play / play-volume projection
- referee effects
- market tickets, handle, consensus, sportsbook odds, opening/closing lines, or external handicapper projections

Some football concepts may be partially reflected indirectly in the existing aggregate team metrics; that is not equivalent to having a separately identified, PIT-safe feature family.

## Market-data firewall

`joint_model.py::_assert_market_blind(...)` recursively rejects direct market-derived keys including spread, total, line, price, American/decimal odds, implied/no-vig probabilities, sportsbook/book identity, closing line/price, moneyline, and generic odds. Market thresholds are read out only after the score distribution exists.

## Live PIT contract

The canonical runner now requires:

1. both teams are in the frozen FBS membership snapshot;
2. execution time is before game start;
3. every team metric has an aware `feature_asof_ts` no later than execution time and strictly before kickoff;
4. `CURRENT_SEASON_PRIOR_WEEKS` metrics are from the target season and have `through_week <= game.week - 1`;
5. Week 1 `PRIOR_SEASON_FALLBACK` metrics actually come from the immediately prior season;
6. unknown metric sample-source contracts fail closed;
7. sportsbook quote timestamps are no later than execution time and strictly before kickoff.

`fetch_cfbd_team_metrics(...)` implements the same intended split: Week 2+ uses current-season metrics through `week - 1`; Week 1 switches to prior-season data.

## Historical PIT materialization

`sportsedge/sports/cfb/historical_features.py` now provides a deterministic materializer for already-frozen historical snapshots. It builds the exact row shape consumed by `CFB_JOINT_GAME_FEATURES_V1` while requiring:

- season-specific frozen FBS membership;
- Week 2+ current-season metrics from exactly `game.week - 1`;
- Week 1 an explicit immediately-prior-season fallback snapshot;
- metric `feature_asof_ts` strictly before kickoff;
- no market/odds/closing-line fields in historical game rows;
- paired realized-score targets and optional paired regulation-score targets;
- deterministic ordering by season/week/game identity.

This closes the row-materialization semantic gap, but **does not prove historical source availability by itself**. The materializer deliberately consumes already-frozen metric/weather snapshots. A source-freeze/manifest layer still must prove where those snapshots came from, when they were available, and that later corrections were not silently backfilled into earlier as-of states. Walk-forward/OOS validation must then consume those frozen rows rather than ex-post reconstructed data.

## Remaining provenance gaps

Weather values are currently normalized from CFBD and carry a source label, but the weather object does not yet carry a retrieval timestamp or independent as-of timestamp. That prevents a complete timestamp-level weather provenance proof and should remain an explicit gap rather than being inferred as solved.

`sportsedge/sports/cfb/history.py` still only bulk-ingests season `games` and `lines`; it is not itself the snapshot-freeze/source-manifest layer for the new historical feature materializer. Durable multi-season source manifests, correction policy, and execution evidence remain required before predictive/OOS promotion evidence can be considered complete.

## Promotion status

None of this implementation trace changes promotion state. FBS-only classification does not create FBS predictive validation, and it creates no FCS validation. No CFB derivative market inherits the full-game model's implementation status. Frozen Truth Gate floors and durable market-specific OOS/CLV/calibration/ROI evidence remain separate prerequisites for OFFICIAL eligibility.
