# MLB full-game market coherence audit (2026-10-13)

Base: `main` @ 655715907. Research note; no production change.

## Question
Are MONEYLINE, RUN_LINE, TOTALS and TEAM_TOTALS priced from ONE joint run
distribution (consistent push mass, integer lines, alternate ladders) or from
separate formulas?

## Finding: canonical path is already joint
* `engine_registry.engine_registry()` routes all four markets to one
  `shared_game_engine.build_shared_game_engine_session()` closure per card.
* That closure simulates one `v7_distribution.simulate_game_distribution`
  (mode `INDEPENDENT_NB`, team r = 3.1311, extras mean 0.7541, 100k paths,
  identity-hash seed) per (game, means, feature hash), caches it, and settles every
  selection from the same `joint_score_pmf` through
  `game_distribution_readout.read_game_probability`. Push mass on integer lines is
  read directly off the PMF; ladders are monotone by construction.
* The selected line/side never enters the stochastic identity, so alternate
  lines for the same game share one PMF.

## Secondary paths (separate formulas / duplication)
1. `generic_market_engine._game_probability` re-implements the four readouts inline
   (same simulator, same identity seed) instead of calling
   `read_game_probability`. Numerically consistent today, but two settlement
   implementations can drift. It also passes `total_line` into the simulator
   (affects only the scalar `over/under/push` fields, not the PMF). Recommend
   consolidating onto `read_game_probability` (integration lane).
2. `team_half_pricing._estimate` prices MLB `TEAM_TOTAL` with an independent
   **Poisson** marginal (`_poisson_outcome`) and F5 with an unfitted 5/9 scale. That
   is a separate, underdispersed formula, inconsistent with the NB joint PMF. It is
   labelled research/WATCH and no caller in `sportsedge/` or `scripts/` was found,
   but it should stay non-authoritative or be retired.
3. Model limitations of the joint path (not incoherence): runs are independent
   between teams conditional on means (no shared game-environment correlation);
   extras use an aggregate-run approximation (home walk-off wins by exactly 1;
   postseason refused); MC error ~0.0016 sd at 100k paths on a 0.5 probability.

## Built (research only, not registered)
`sportsedge/research/mlb_joint_team_runs.py`: exact analytic joint PMF (no MC).
* `INDEPENDENT_NB` reproduces the production simulator semantics; tests confirm
  agreement with the MC simulator and the live TEAM_TOTALS engine within 4 MC sd.
* `SHARED_PACE_NB` adds a mean-one Gamma(shared_r) game-pace frailty (positive
  team-run correlation, team means preserved). `shared_r` has no default and is
  not fitted here; see `docs/MLB_JOINT_TEAM_RUNS_2027_PREREG.md`.
* All four markets settle via the production `read_game_probability`.
Tests: `tests/test_mlb_joint_team_runs_research.py` (normalization, no final ties,
integer push = point mass, half-line zero push, complements, monotone total /
team-total / run-line ladders, team-total vs PMF coherence, MC + live-engine
agreement, fail-closed inputs, not registered).

## Source identity (pitcher/batter) — added fail-closed checks
New `sportsedge/mlb_source_identity.py`:
* `check_split_identity`: a gameLog split carrying `player.id`/`team.id` that
  differs from the requested id refuses the whole response (absent = endpoint
  scoped, tolerated, never inferred).
* `refuse_conflicting_game_pk`: duplicate gamePk with different stats refuses;
  identical duplicates collapse.
* `bind_source_record`: a pregame record must carry and match game_pk, player_id
  and team_id (missing = refused).
Wired into `mlb_public_pitcher_history.prior_starts` and
`mlb_public_batter_history.prior_games` (previously: no per-split player check,
silent first-wins on conflicting duplicate gamePk).

NOT wired into `mlb_generic_features` (the canonical feature path): that file is
pinned by the MLB model-artifact manifest (`MLB_MODEL_ARTIFACT_SURFACE_MISMATCH`),
so changing it is a governed re-pin. Its `_splits`/`player_rows`/`team_rows` have
the same gaps (no split player/team check, no gamePk dedupe). The proposed diff is
in `docs/proposals/MLB_GENERIC_FEATURES_SOURCE_IDENTITY_20261013.patch` for the
integration lane to apply with a manifest re-pin.
