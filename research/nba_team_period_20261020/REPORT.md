# NBA team-total & period engine — build report (wave 3)

Engine: `sportsedge/nba_team_period_engine.py`
(`NBA_TEAM_PERIOD_RATINGS_V1`). Screen: `screen_nba_team_period.py`
in this directory; full-precision output `screen_results_v1.json`.
Full build report:
`~/workspace/sportsedge/nba_team_period_engines_20261020/BUILD_REPORT.md`.

Construction: the Oct 18 backtest-everything sweep's B4/B11
calibration constructions, implemented unchanged — spec
`backtest_everything_20261018/specs/SPEC_NBA_GAME_LEVEL_V1.md`
(sha256 cc96783f…), machinery imported from main
(`ratings_model.NBARatings` committed defaults;
`period_history.fit_period_parameters` under the frozen fit protocol:
span seasons ≤2014, day-granularity mapping, as_of 2015-10-01 UTC).
Gates: ≥10 prior in-season games per team and ≥200 prior in-season
league team-games, fail-closed.

Screen (ONCE, through the engine, SBR archive vintage sha256
0c985848… — byte-identical to the sweep's pin; CALIBRATION ONLY, no
market leg exists for these families):

- TEAM_TOTAL — CALIBRATED_CANDIDATE, **exact reproduction** of the
  published B4 (parity max abs diff 0 on every figure): n=15,506,
  MAE 8.9975 vs B1 9.5411 / B2 9.8275.
- TEAM_QUARTER_TOTAL — CALIBRATED_CANDIDATE, **exact reproduction**
  of the published B11 (parity 0 incl. per-quarter table and the fit
  version NBA_PERIOD_FIT_V1:310b42f5bc41): n=62,024, MAE 4.6103 vs
  4.7070 / 4.7099.
- GAME_QUARTER_TOTAL — CALIBRATED_CANDIDATE, FIRST screen of the
  mechanical aggregation: n=31,012, MAE 6.6518 vs 6.7483 / 6.8135.
- TEAM_HALF_TOTAL — CALIBRATED_CANDIDATE, FIRST screen: n=31,012,
  MAE 6.4541 vs 6.6358 / 6.7228.
- GAME_HALF_TOTAL — CALIBRATED_CANDIDATE, FIRST screen: n=15,506,
  MAE 9.7481 vs 9.9512 / 10.1957.

All paired CIs entirely below zero vs both baselines (214 ISO-week
blocks, seed 20261018 — see the results JSON for endpoints).

Not built: period spreads/moneylines (NO_CONSTRUCTION — no sanctioned
construction exists; the shares construction yields period points
only) and player period props (NO_CONSTRUCTION + NO_DATA).

Data-path finding: the maintained sportsdataverse assets carry NO
quarter scores (team-boxscores asset inspected directly 2026-10-20:
full-game stats only), so period outcomes are NO_DATA on the
maintained path — period forecasts price only from supplied
`NBAPeriodObservation`-form history and otherwise refuse
`NBA_PERIOD_FIT_HISTORY_MISSING` / `NBA_PERIOD_HISTORY_UNAVAILABLE`.
Team totals have a maintained path (team points per game; dates join
on game_id via `games_from_team_boxscores()`).

Tests: 9 new passed; NBA slice 164 passed vs 155 on pristine base
(delta = the 9 new; failure sets identical, empty). Governance
unchanged: no registration, eligibility, or validation state was
modified for any family; no runner wiring.
