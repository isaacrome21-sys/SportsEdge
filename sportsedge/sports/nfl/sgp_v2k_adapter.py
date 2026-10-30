"""Bridge the V2K drive simulator into the NFL SGP same-path contract.

V2K already produces a sequential joint score path.  This adapter preserves one
record per simulation seed so game legs and later player-stat overlays can be
evaluated on exactly the same simulated world.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from sportsedge.sports.nfl.v2k_drive_core import (
    HierarchicalStrength,
    SimulationResult,
    simulate_joint_game,
)


class NFLV2KSGPAdapterError(ValueError):
    pass


def simulation_result_to_sgp_path(
    result: SimulationResult,
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    seed: int,
    players: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not game_id or not home_team or not away_team or home_team == away_team:
        raise NFLV2KSGPAdapterError("NFL_SGP_V2K_IDENTITY_INVALID")
    if int(result.home_score) < 0 or int(result.away_score) < 0:
        raise NFLV2KSGPAdapterError("NFL_SGP_V2K_SCORE_INVALID")
    return {
        "game_id": str(game_id),
        "simulation_seed": int(seed),
        "home_team": str(home_team),
        "away_team": str(away_team),
        "home_score": int(result.home_score),
        "away_score": int(result.away_score),
        "margin": int(result.margin),
        "total": int(result.total),
        "team_totals": dict(result.team_totals),
        "players": {str(k): dict(v) for k, v in (players or {}).items()},
        "drive_path": [dict(row) for row in result.path],
        "simulation_source": "V2K_DRIVE_CORE",
    }


def simulate_v2k_sgp_paths(
    model: HierarchicalStrength,
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    seeds: Iterable[int],
    regulation_drives: int | None = None,
    max_overtime_drives: int = 8,
) -> list[dict[str, Any]]:
    """Generate deterministic per-seed V2K paths for downstream SGP evaluation."""
    seed_list = [int(seed) for seed in seeds]
    if not seed_list:
        raise NFLV2KSGPAdapterError("NFL_SGP_V2K_SEEDS_REQUIRED")
    if len(set(seed_list)) != len(seed_list):
        raise NFLV2KSGPAdapterError("NFL_SGP_V2K_DUPLICATE_SEED")

    output: list[dict[str, Any]] = []
    for seed in seed_list:
        result = simulate_joint_game(
            model,
            home_team,
            away_team,
            seed=seed,
            regulation_drives=regulation_drives,
            max_overtime_drives=max_overtime_drives,
        )
        output.append(
            simulation_result_to_sgp_path(
                result,
                game_id=game_id,
                home_team=home_team,
                away_team=away_team,
                seed=seed,
            )
        )
    return output


def attach_player_stats_by_seed(
    paths: Iterable[Mapping[str, Any]],
    player_stats_by_seed: Mapping[int | str, Mapping[str, Mapping[str, Any]]],
    *,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """Attach player outcomes generated for the exact same simulation seeds.

    This function deliberately does not fabricate player outcomes from game score.
    A separate player simulator must supply the seed-bound records.  In strict
    mode every game path must have a player overlay, preventing accidental use of
    marginal/bucketed prop probabilities as if they were joint simulations.
    """
    output: list[dict[str, Any]] = []
    for source in paths:
        path = dict(source)
        if "simulation_seed" not in path:
            raise NFLV2KSGPAdapterError("NFL_SGP_V2K_PATH_SEED_REQUIRED")
        seed = int(path["simulation_seed"])
        stats = player_stats_by_seed.get(seed)
        if stats is None:
            stats = player_stats_by_seed.get(str(seed))
        if stats is None:
            if strict:
                raise NFLV2KSGPAdapterError(f"NFL_SGP_V2K_PLAYER_OVERLAY_MISSING:{seed}")
            path["players"] = {}
            path["player_overlay_status"] = "MISSING"
        else:
            path["players"] = {str(player): dict(row) for player, row in stats.items()}
            path["player_overlay_status"] = "SAME_SEED_ATTACHED"
        output.append(path)
    return output
