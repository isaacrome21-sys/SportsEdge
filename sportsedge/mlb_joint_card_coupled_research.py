"""Research-only MLB game/pitcher coupling with pathwise score compatibility.

This is the successor research lane to ``mlb_joint_card_research``. The V7 game
score paths are reproduced exactly. Pitcher states still come from one whole,
strictly-prior historical start row, but the sampled row is now conditioned on the
simulated opponent final score so an impossible state (pitcher ER > opponent team
runs) cannot be emitted.

Conditioning contract:
* draw one prior start row from a pitcher-specific RNG stream;
* if its ER is compatible with the simulated opponent score, keep it unchanged;
* otherwise resample uniformly from prior starts with ER <= opponent runs;
* if the finite history has no feasible row, keep the sampled row's K/outs/H/BB
  and cap ER to opponent runs. The fallback is counted explicitly.

The fallback is a support repair, not evidence of calibrated dependence. Therefore
all output remains NOT_MODEL_P / NOT Truth Gate / NOT OFFICIAL. Promotion requires
separate temporal validation of the joint dependence, not merely these invariants.
"""
from __future__ import annotations

from math import exp, isfinite
from typing import Any, Mapping, Sequence

from .identity_rng import candidate_rng
from .mlb_joint_card_research import (
    GAME_MARKETS,
    PITCHER_MARKETS,
    MLBJointCardResearchError,
    _finite_positive,
    _normalize_pool,
    _settle,
)
from .source_lineage import canonical_json_sha256
from .v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    V7_DISTRIBUTION_VERSION,
    _poisson,
    _resolve_extras,
)

JOINT_COUPLED_RESEARCH_VERSION = "mlb_game_pitcher_score_compatible_paths_research_v2"
PITCHER_COUPLING = "same_path_score_compatible_whole_start_bootstrap_v2"


def _normalize_pitcher_sides(
    *,
    pools: Mapping[str, Sequence[Mapping[str, Any]]],
    pitcher_team_sides: Mapping[str, str] | None,
) -> dict[str, str]:
    sides_in = pitcher_team_sides or {}
    out: dict[str, str] = {}
    for pitcher_id in pools:
        side = str(sides_in.get(pitcher_id) or "").upper()
        if side not in {"AWAY", "HOME"}:
            raise MLBJointCardResearchError(
                f"pitcher {pitcher_id} requires pitcher_team_sides AWAY/HOME for score coupling"
            )
        out[str(pitcher_id)] = side
    extra = set(str(key) for key in sides_in) - set(str(key) for key in pools)
    if extra:
        raise MLBJointCardResearchError(f"pitcher_team_sides has unknown pitcher ids: {sorted(extra)}")
    return out


def _uniform_row(pool: Sequence[Mapping[str, int]], rng) -> Mapping[str, int]:
    return pool[min(len(pool) - 1, int(rng.random() * len(pool)))]


def _score_compatible_row(
    *,
    pool: Sequence[Mapping[str, int]],
    opponent_runs: int,
    rng,
) -> tuple[dict[str, int], str]:
    """Return a row satisfying the hard baseball identity ER <= opponent runs.

    The preferred path keeps an untouched whole historical row. If the first draw
    is infeasible, resampling remains whole-row. Only when the finite prior-start
    support contains no feasible ER value do we alter ER, and that support repair
    is surfaced as ``CAPPED_SUPPORT_FALLBACK`` rather than hidden.
    """
    if opponent_runs < 0:
        raise MLBJointCardResearchError("opponent_runs must be nonnegative")
    first = dict(_uniform_row(pool, rng))
    if int(first["earned_runs"]) <= opponent_runs:
        return first, "DIRECT"
    feasible = [row for row in pool if int(row["earned_runs"]) <= opponent_runs]
    if feasible:
        return dict(_uniform_row(feasible, rng)), "RESAMPLED_FEASIBLE"
    first["earned_runs"] = int(opponent_runs)
    return first, "CAPPED_SUPPORT_FALLBACK"


def simulate_score_compatible_joint_card(
    *,
    game_id: str,
    away_mean_runs: Any,
    home_mean_runs: Any,
    feature_source_hash: str | None,
    selections: Sequence[Mapping[str, Any]],
    pitcher_pools: Mapping[str, Sequence[Mapping[str, Any]]],
    pitcher_team_sides: Mapping[str, str] | None,
    simulations: int = 100000,
    shared_game_sigma: float = 0.12,
    team_sigma: float = 0.08,
    extra_half_inning_mean: float = DEFAULT_EXTRA_HALF_INNING_MEAN,
) -> dict[str, Any]:
    """Price game and pitcher rows from one deterministic, score-compatible path set."""
    game_id = str(game_id or "").strip()
    if not game_id:
        raise MLBJointCardResearchError("game_id required")
    away_mean = _finite_positive(away_mean_runs, "away_mean_runs")
    home_mean = _finite_positive(home_mean_runs, "home_mean_runs")
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise MLBJointCardResearchError("simulations must be >= 1000")
    simulations = int(simulations)
    if not selections:
        raise MLBJointCardResearchError("selections required")

    normalized_pools = {
        str(pid): _normalize_pool(pool, str(pid))
        for pid, pool in sorted(pitcher_pools.items(), key=lambda item: str(item[0]))
    }
    pitcher_sides = _normalize_pitcher_sides(
        pools=normalized_pools,
        pitcher_team_sides=pitcher_team_sides,
    )

    normalized_selections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    used_pitchers: set[str] = set()
    for i, raw in enumerate(selections):
        if not isinstance(raw, Mapping):
            raise MLBJointCardResearchError(f"selection[{i}] must be an object")
        row = dict(raw)
        selection_id = str(row.get("selection_id") or f"selection-{i}")
        if selection_id in seen_ids:
            raise MLBJointCardResearchError(f"duplicate selection_id {selection_id}")
        seen_ids.add(selection_id)
        market = str(row.get("market") or "").upper()
        if market not in GAME_MARKETS | PITCHER_MARKETS:
            raise MLBJointCardResearchError(f"unsupported joint market {market}")
        if market in PITCHER_MARKETS:
            pitcher_id = str(row.get("pitcher_id") or "")
            if pitcher_id not in normalized_pools:
                raise MLBJointCardResearchError(f"missing pitcher pool for {pitcher_id or 'UNKNOWN'}")
            used_pitchers.add(pitcher_id)
        row["selection_id"] = selection_id
        row["market"] = market
        normalized_selections.append(row)

    unused = set(normalized_pools) - used_pitchers
    if unused:
        raise MLBJointCardResearchError(f"unused pitcher pools are not allowed: {sorted(unused)}")

    stochastic_identity = {
        "engine": V7_DISTRIBUTION_VERSION,
        "game_id": game_id,
        "away_mean_runs": away_mean,
        "home_mean_runs": home_mean,
        "feature_source_hash": feature_source_hash,
    }
    score_build_hash = canonical_json_sha256(stochastic_identity)
    score_rng = candidate_rng(score_build_hash)

    pool_hashes = {pid: canonical_json_sha256(pool) for pid, pool in normalized_pools.items()}
    simulation_identity = {
        "joint_engine": JOINT_COUPLED_RESEARCH_VERSION,
        "score_build_hash": score_build_hash,
        "simulations": simulations,
        "pitcher_pool_sha256": pool_hashes,
        "pitcher_team_sides": pitcher_sides,
        "pitcher_coupling": PITCHER_COUPLING,
    }
    simulation_id = canonical_json_sha256(simulation_identity)
    pitcher_rngs = {
        pid: candidate_rng(canonical_json_sha256({
            "joint_engine": JOINT_COUPLED_RESEARCH_VERSION,
            "simulation_id": simulation_id,
            "pitcher_id": pid,
            "team_side": pitcher_sides[pid],
            "pool_sha256": pool_hashes[pid],
        }))
        for pid in normalized_pools
    }

    counters = {
        row["selection_id"]: {"wins": 0, "pushes": 0, "losses": 0}
        for row in normalized_selections
    }
    compatibility = {
        pid: {
            "team_side": pitcher_sides[pid],
            "direct_paths": 0,
            "resampled_feasible_paths": 0,
            "capped_support_fallback_paths": 0,
            "earned_runs_excess_paths": 0,
        }
        for pid in normalized_pools
    }
    score_counts: dict[tuple[int, int], int] = {}
    away_sum = home_sum = 0
    le5 = eq6 = ge7 = 0

    shared_sigma = float(shared_game_sigma)
    idio_sigma = float(team_sigma)
    extras_mean = float(extra_half_inning_mean)
    if not all(isfinite(x) for x in (shared_sigma, idio_sigma, extras_mean)):
        raise MLBJointCardResearchError("score dispersion parameters must be finite")
    if shared_sigma < 0 or idio_sigma < 0 or extras_mean <= 0:
        raise MLBJointCardResearchError("invalid score dispersion parameters")

    for _ in range(simulations):
        shared = score_rng.gauss(0.0, shared_sigma)
        away_noise = score_rng.gauss(0.0, idio_sigma)
        home_noise = score_rng.gauss(0.0, idio_sigma)
        away_lam = away_mean * exp(shared + away_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        home_lam = home_mean * exp(shared + home_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        away = _poisson(score_rng, away_lam)
        home = _poisson(score_rng, home_lam)
        if away == home:
            away, home = _resolve_extras(
                score_rng,
                away,
                home,
                away_lam=away_lam,
                home_lam=home_lam,
                extra_half_inning_mean=extras_mean,
            )

        score_counts[(away, home)] = score_counts.get((away, home), 0) + 1
        away_sum += away
        home_sum += home
        total = away + home
        if total <= 5:
            le5 += 1
        elif total == 6:
            eq6 += 1
        else:
            ge7 += 1

        sampled_pitchers: dict[str, Mapping[str, int]] = {}
        for pid, pool in normalized_pools.items():
            opponent_runs = home if pitcher_sides[pid] == "AWAY" else away
            sampled, mode = _score_compatible_row(
                pool=pool,
                opponent_runs=int(opponent_runs),
                rng=pitcher_rngs[pid],
            )
            compatibility[pid][
                {
                    "DIRECT": "direct_paths",
                    "RESAMPLED_FEASIBLE": "resampled_feasible_paths",
                    "CAPPED_SUPPORT_FALLBACK": "capped_support_fallback_paths",
                }[mode]
            ] += 1
            if int(sampled["earned_runs"]) > int(opponent_runs):
                compatibility[pid]["earned_runs_excess_paths"] += 1
            sampled_pitchers[pid] = sampled

        for row in normalized_selections:
            settled = _settle(row, away=away, home=home, pitchers=sampled_pitchers)
            bucket = counters[row["selection_id"]]
            if settled > 0:
                bucket["wins"] += 1
            elif settled == 0:
                bucket["pushes"] += 1
            else:
                bucket["losses"] += 1

    joint_score_pmf = {
        f"{away},{home}": count / simulations
        for (away, home), count in sorted(score_counts.items())
    }
    score_distribution_sha256 = canonical_json_sha256({
        "version": V7_DISTRIBUTION_VERSION,
        "simulations": simulations,
        "seed_policy": "identity_sha256_256bit",
        "joint_score_pmf": joint_score_pmf,
    })

    game_script = {
        "runs_le_5_p": le5 / simulations,
        "runs_eq_6_p": eq6 / simulations,
        "runs_ge_7_p": ge7 / simulations,
        "over_6_win_p": ge7 / simulations,
        "over_6_push_p": eq6 / simulations,
        "away_mean_runs": away_sum / simulations,
        "home_mean_runs": home_sum / simulations,
        "total_mean_runs": (away_sum + home_sum) / simulations,
    }
    script_mass = (
        game_script["runs_le_5_p"]
        + game_script["runs_eq_6_p"]
        + game_script["runs_ge_7_p"]
    )
    if abs(script_mass - 1.0) > 1e-12:
        raise MLBJointCardResearchError("game-script mass does not conserve")
    if any(row["earned_runs_excess_paths"] for row in compatibility.values()):
        raise MLBJointCardResearchError("score-compatible coupling emitted ER above opponent runs")

    results: list[dict[str, Any]] = []
    for row in normalized_selections:
        count = counters[row["selection_id"]]
        result = dict(row)
        result.update({
            "research_p": count["wins"] / simulations,
            "push_p": count["pushes"] / simulations,
            "loss_p": count["losses"] / simulations,
            "simulation_id": simulation_id,
            "mc_paths": simulations,
            "score_distribution_sha256": score_distribution_sha256,
            "joint_research_version": JOINT_COUPLED_RESEARCH_VERSION,
        })
        results.append(result)

    return {
        "schema_version": 2,
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_evidence": False,
        "joint_research_version": JOINT_COUPLED_RESEARCH_VERSION,
        "simulation_id": simulation_id,
        "mc_paths": simulations,
        "score_build_hash": score_build_hash,
        "score_distribution_sha256": score_distribution_sha256,
        "score_engine_version": V7_DISTRIBUTION_VERSION,
        "pitcher_pool_sha256": pool_hashes,
        "pitcher_team_sides": pitcher_sides,
        "pitcher_coupling": PITCHER_COUPLING,
        "pitcher_score_compatibility": compatibility,
        "game_script": game_script,
        "consistency": {
            "game_script_mass": script_mass,
            "over_6_equals_runs_ge_7": game_script["over_6_win_p"] == game_script["runs_ge_7_p"],
            "all_results_same_simulation_id": all(r["simulation_id"] == simulation_id for r in results),
            "all_results_same_score_distribution": all(
                r["score_distribution_sha256"] == score_distribution_sha256 for r in results
            ),
            "pitcher_er_never_exceeds_opponent_runs": all(
                row["earned_runs_excess_paths"] == 0 for row in compatibility.values()
            ),
        },
        "limitations": {
            "score_conditioning": "hard ER<=opponent-runs support constraint only",
            "support_fallback": "if no prior row is feasible, ER is capped and the path is counted",
            "calibrated_dependence": False,
            "promotion_allowed": False,
        },
        "results": results,
    }
