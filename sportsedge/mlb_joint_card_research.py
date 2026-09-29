"""Research-only coherent MLB card simulator.

This module fixes a presentation/modeling failure exposed by the Sept. 29 card:
game lines, team totals, game-script bins, and supported pitcher props can now be
read from one deterministic path set with one simulation_id.

The score component intentionally reproduces the existing V7 full-game draw
sequence for the same game state. Pitcher outcomes are sampled as whole strictly-
prior start rows on those same path indexes. That preserves within-pitcher stat
coherence (K/outs/ER/H/BB come from the same historical start row) and prevents
two players from inheriting one generic fallback probability.

Important limitation: the pitcher-start bootstrap is conditionally independent of
the simulated final score. This is a research coupling contract, not promotion
evidence. Output is NOT Model_P / NOT Truth Gate / NOT OFFICIAL until a validated
score-to-pitcher dependence model exists and clears the normal gates.
"""
from __future__ import annotations

from math import exp, isfinite
from typing import Any, Mapping, Sequence

from .identity_rng import candidate_rng
from .source_lineage import canonical_json_sha256
from .v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    V7_DISTRIBUTION_VERSION,
    _poisson,
    _resolve_extras,
)

JOINT_RESEARCH_VERSION = "mlb_game_pitcher_joint_paths_research_v1"
GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})
PITCHER_MARKETS = frozenset({
    "PITCHER_K",
    "PITCHER_OUTS",
    "PITCHER_ER",
    "PITCHER_HITS_ALLOWED",
    "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER",
})
_REQUIRED_PITCHER_FIELDS = (
    "strikeouts",
    "outs",
    "earned_runs",
    "hits_allowed",
    "walks_allowed",
)


class MLBJointCardResearchError(ValueError):
    pass


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise MLBJointCardResearchError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBJointCardResearchError(f"{name} must be numeric") from exc
    if not isfinite(out) or out <= 0:
        raise MLBJointCardResearchError(f"{name} must be finite and > 0")
    return out


def _normalize_pool(raw: Any, pitcher_id: str) -> list[dict[str, int]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MLBJointCardResearchError(f"pitcher {pitcher_id} history must be a sequence")
    rows: list[dict[str, int]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise MLBJointCardResearchError(f"pitcher {pitcher_id} history[{i}] must be an object")
        row: dict[str, int] = {}
        for field in _REQUIRED_PITCHER_FIELDS:
            value = item.get(field)
            if isinstance(value, bool):
                raise MLBJointCardResearchError(f"pitcher {pitcher_id} history[{i}].{field} invalid")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise MLBJointCardResearchError(
                    f"pitcher {pitcher_id} history[{i}].{field} invalid"
                ) from exc
            if not isfinite(number) or number < 0 or int(number) != number:
                raise MLBJointCardResearchError(f"pitcher {pitcher_id} history[{i}].{field} invalid")
            row[field] = int(number)
        if not 0 <= row["outs"] <= 27:
            raise MLBJointCardResearchError(f"pitcher {pitcher_id} outs outside [0,27]")
        rows.append(row)
    if len(rows) < 5:
        raise MLBJointCardResearchError(f"pitcher {pitcher_id} requires at least 5 prior starts")
    return rows


def _pitcher_value(row: Mapping[str, int], market: str) -> int:
    if market == "PITCHER_K":
        return int(row["strikeouts"])
    if market == "PITCHER_OUTS":
        return int(row["outs"])
    if market == "PITCHER_ER":
        return int(row["earned_runs"])
    if market == "PITCHER_HITS_ALLOWED":
        return int(row["hits_allowed"])
    if market == "PITCHER_BB":
        return int(row["walks_allowed"])
    if market == "PITCHER_HITS_WALKS_ER":
        return int(row["hits_allowed"] + row["walks_allowed"] + row["earned_runs"])
    raise MLBJointCardResearchError(f"unsupported pitcher market {market}")


def _settle(selection: Mapping[str, Any], *, away: int, home: int, pitchers: Mapping[str, Mapping[str, int]]) -> int:
    """Return 1=win, 0=push, -1=loss for one path."""
    market = str(selection.get("market") or "").upper()
    side = str(selection.get("side") or "").upper()
    try:
        line = float(selection.get("line"))
    except (TypeError, ValueError) as exc:
        raise MLBJointCardResearchError("selection line must be numeric") from exc
    if not isfinite(line):
        raise MLBJointCardResearchError("selection line must be finite")

    if market == "MONEYLINE":
        if side == "AWAY":
            return 1 if away > home else -1
        if side == "HOME":
            return 1 if home > away else -1
        raise MLBJointCardResearchError("MONEYLINE side must be AWAY/HOME")

    if market == "RUN_LINE":
        if side == "AWAY":
            margin = float(away) + line - float(home)
        elif side == "HOME":
            margin = float(home) + line - float(away)
        else:
            raise MLBJointCardResearchError("RUN_LINE side must be AWAY/HOME")
        if margin > 0:
            return 1
        if margin < 0:
            return -1
        return 0

    if market == "TOTALS":
        observed = float(away + home)
    elif market == "TEAM_TOTALS":
        team_side = str(selection.get("team_side") or "").upper()
        if team_side == "AWAY":
            observed = float(away)
        elif team_side == "HOME":
            observed = float(home)
        else:
            raise MLBJointCardResearchError("TEAM_TOTALS requires team_side AWAY/HOME")
    elif market in PITCHER_MARKETS:
        pitcher_id = str(selection.get("pitcher_id") or "")
        if not pitcher_id or pitcher_id not in pitchers:
            raise MLBJointCardResearchError(f"{market} requires a bound pitcher_id")
        observed = float(_pitcher_value(pitchers[pitcher_id], market))
    else:
        raise MLBJointCardResearchError(f"unsupported joint market {market}")

    if side == "OVER":
        if observed > line:
            return 1
        if observed < line:
            return -1
        return 0
    if side == "UNDER":
        if observed < line:
            return 1
        if observed > line:
            return -1
        return 0
    raise MLBJointCardResearchError(f"{market} side must be OVER/UNDER")


def simulate_joint_card(
    *,
    game_id: str,
    away_mean_runs: Any,
    home_mean_runs: Any,
    feature_source_hash: str | None,
    selections: Sequence[Mapping[str, Any]],
    pitcher_pools: Mapping[str, Sequence[Mapping[str, Any]]],
    simulations: int = 100000,
    shared_game_sigma: float = 0.12,
    team_sigma: float = 0.08,
    extra_half_inning_mean: float = DEFAULT_EXTRA_HALF_INNING_MEAN,
) -> dict[str, Any]:
    """Price supported selections from one deterministic path index.

    Score draws use the exact V7 RNG identity and draw order. Pitcher histories use
    separate deterministic RNG streams so sampling pitcher states cannot perturb
    the V7 score paths. Every displayed result still binds to the same path count
    and simulation_id.
    """
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

    normalized_selections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
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
        row["selection_id"] = selection_id
        row["market"] = market
        normalized_selections.append(row)

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
        "joint_engine": JOINT_RESEARCH_VERSION,
        "score_build_hash": score_build_hash,
        "simulations": simulations,
        "pitcher_pool_sha256": pool_hashes,
        "pitcher_coupling": "same_path_whole_start_bootstrap_score_independent",
    }
    simulation_id = canonical_json_sha256(simulation_identity)
    pitcher_rngs = {
        pid: candidate_rng(canonical_json_sha256({
            "joint_engine": JOINT_RESEARCH_VERSION,
            "simulation_id": simulation_id,
            "pitcher_id": pid,
            "pool_sha256": pool_hashes[pid],
        }))
        for pid in normalized_pools
    }

    counters = {
        row["selection_id"]: {"wins": 0, "pushes": 0, "losses": 0}
        for row in normalized_selections
    }
    score_counts: dict[tuple[int, int], int] = {}
    away_sum = home_sum = 0
    le5 = eq6 = ge7 = 0

    shared_sigma = float(shared_game_sigma)
    idio_sigma = float(team_sigma)
    extras_mean = float(extra_half_inning_mean)
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
            rng = pitcher_rngs[pid]
            sampled_pitchers[pid] = pool[min(len(pool) - 1, int(rng.random() * len(pool)))]

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
    script_mass = game_script["runs_le_5_p"] + game_script["runs_eq_6_p"] + game_script["runs_ge_7_p"]
    if abs(script_mass - 1.0) > 1e-12:
        raise MLBJointCardResearchError("game-script mass does not conserve")

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
            "joint_research_version": JOINT_RESEARCH_VERSION,
        })
        results.append(result)

    return {
        "schema_version": 1,
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_evidence": False,
        "joint_research_version": JOINT_RESEARCH_VERSION,
        "simulation_id": simulation_id,
        "mc_paths": simulations,
        "score_build_hash": score_build_hash,
        "score_distribution_sha256": score_distribution_sha256,
        "score_engine_version": V7_DISTRIBUTION_VERSION,
        "pitcher_pool_sha256": pool_hashes,
        "pitcher_coupling": "same_path_whole_start_bootstrap_score_independent",
        "game_script": game_script,
        "consistency": {
            "game_script_mass": script_mass,
            "over_6_equals_runs_ge_7": game_script["over_6_win_p"] == game_script["runs_ge_7_p"],
            "all_results_same_simulation_id": all(r["simulation_id"] == simulation_id for r in results),
            "all_results_same_score_distribution": all(
                r["score_distribution_sha256"] == score_distribution_sha256 for r in results
            ),
        },
        "results": results,
    }
