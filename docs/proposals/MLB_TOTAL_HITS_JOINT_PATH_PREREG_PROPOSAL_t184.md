# PROPOSAL (NOT FROZEN): MLB game/team Total Hits joint-path harness preregistration

Status: **DRAFT PROPOSAL, UNFROZEN.** Only the owner can freeze it. This file grants no authority: it doesn't allow any evaluation, activation, capture, admission or promotion. No scoring, fold inspection or parameter inspection has happened.

## Candidate under test
- Construction: `sportsedge.research.mlb_joint_total_hits.read_joint_total_hits`, as in PR #2334, with the conservation refusals from fix commit `db05d023` (branch `grok/t180-total-hits-red-fix-20261015`). Those refusals clear all 16 tests in the #2336 RED conservation battery.
- Markets: `GAME_TOTAL_HITS` and `TEAM_TOTAL_HITS`, each scored separately.
- Path source: `sportsedge.dfs.mlb_joint_paths.simulate_mlb_joint_paths` with fixed nine-player lineups. Substitutions are not modelled and must stay a declared limitation.
- The owner's freeze inherits the following unchanged from the owner's source prereg, and this proposal does not choose them: path count, seed policy, line grids, typical lines and ECE tolerance. **OWNER TO INSERT the exact source-prereg values and their hash before freezing.** The source prereg isn't in the repo at main `f113a3e8`.

## Comparators (scored on identical paired rows)
1. The independence-shortcut comparator, which convolves per-batter marginals. The prior source prereg already scores it.
2. The prior FAILED candidate comparator, as in the source prereg.
3. A climatology baseline: a strictly prior empirical game/team hits distribution from verified linescores.
4. Market (proposed, optional): the de-vigged two-sided DK main line, used only where a genuine paired quote with a timestamp before first pitch exists. One-sided ladders are never paired synthetically.

## Metrics and pass rule (proposed)
- Primary metric: ranked probability score (RPS) on the count PMF. Secondary metrics: log loss and Brier on over/under at the typical lines, plus ECE within the source tolerance.
- Uncertainty: a game-clustered bootstrap of the paired metric differences, as in the source prereg.
- PASS conditions: as in the source prereg, all three must hold. **Owner clause 1 (issue #2264, 2026-10-15), verbatim:**
  > The three predeclared PASS conditions must ALL hold separately for each market (GAME_TOTAL_HITS and TEAM_TOTAL_HITS), both in the pooled evaluation across folds AND in every individual validation fold. A pooled PASS cannot override any fold FAIL; a market-level PASS cannot be inferred from the other market.

## Point-in-time (PIT) discipline
**Owner clause 2 (issue #2264, 2026-10-15), verbatim:**
> Within each validation fold, every simulator player input (including per-player hit/PA/outcome rates, shrinkage features and any fitted role/opportunity input) must be derived exclusively from games strictly earlier than the prediction game's cutoff; target-game and later game data are prohibited, even when lineups themselves are pregame.

Additional proposals:
- Lineups must be confirmed with a timestamp before the cutoff. Rows with retrospectively backfilled lineups are excluded, not imputed.
- Folds run chronologically, forward in time, with no shuffling.
- Holdout seasons or windows are declared before freezing, and no holdout is spent without an owner ruling.

## Data
- Only allowed data that is already archived. No credit-consuming collectors.
- The dataset manifest (source, row hashes, PIT cutoffs, fold ids) is published and hashed before any scoring.

## Outcomes
- PASS lets the market be considered `VALIDATED_FOR_FORWARD` (forward shadow) only after independent review. It does not make the market `VERIFIED_EDGE_ELIGIBLE`.
- FAIL is kept as binding negative evidence, and the same holdout is not tuned again.

## Freeze procedure (owner only)
1. Insert the source-prereg values and hash.
2. Publish the exact bytes, hash and commit.
3. Register the governance path.
4. Freeze before any harness runs.
