"""Fail-closed coherent NFL prop research runner.

Consumes PIT-safe player roles plus upstream market-blind game-state paths, runs the
coherent team scoring simulator, and emits market-blind prop estimates. Sportsbook
quotes remain downstream in nfl_prop_run_it_score_b.

Research only: no Model_P, Truth Gate, staking, promotion, or OFFICIAL authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.nfl_coherent_team_scoring import simulate_coherent_team_scoring_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


SUPPORTED = frozenset({
    "passing_yards", "pass_attempts", "completions", "pass_tds",
    "interceptions", "rushing_yards", "rush_attempts",
    "receiving_yards", "receptions", "rush_receiving_yards",
    "anytime_tds",
})


def _price(values: Sequence[int], line: float, selection: str) -> tuple[float, float]:
    side = str(selection).upper()
    if side not in {"OVER", "UNDER"}:
        raise NflPropSimulationError("PROP_SELECTION_INVALID")
    over = sum(v > line for v in values)
    under = sum(v < line for v in values)
    push = len(values) - over - under
    n = float(len(values))
    return ((over if side == "OVER" else under) / n, push / n)


def run_coherent_prop_estimates(
    *,
    game_id: str,
    teams: Sequence[Mapping[str, Any]],
    game_states_by_team: Mapping[str, Sequence[Mapping[str, Any]]],
    markets: Sequence[Mapping[str, Any]],
    seed: int = 21,
) -> list[dict[str, Any]]:
    """Run coherent same-path props and return market-blind probability rows.

    Each team row requires team, qb, and an exhaustive skill_players pool (use an
    explicit OTHER bucket when necessary). Game states must be upstream,
    market-blind and have the same path count for both teams.
    """
    if len(teams) != 2:
        raise NflPropSimulationError("TWO_TEAMS_REQUIRED")
    paths: dict[str, list[dict[str, Any]]] = {}
    player_index: dict[str, tuple[str, str]] = {}
    for i, team in enumerate(teams):
        code = str(team.get("team") or "").upper().strip()
        if not code or code in paths:
            raise NflPropSimulationError("TEAM_IDENTITY_INVALID")
        states = game_states_by_team.get(code)
        if not states:
            raise NflPropSimulationError(f"GAME_STATES_REQUIRED:{code}")
        qb = team.get("qb")
        skills = team.get("skill_players")
        if not isinstance(qb, Mapping) or not isinstance(skills, Sequence) or not skills:
            raise NflPropSimulationError(f"TEAM_PAYLOAD_INVALID:{code}")
        team_paths = simulate_coherent_team_scoring_paths(
            qb, skills, states, seed=int(seed) + i * 1000003
        )
        paths[code] = team_paths
        qbn = str(qb.get("player") or "").strip()
        if not qbn or qbn in player_index:
            raise NflPropSimulationError("PLAYER_IDENTITY_DUPLICATE")
        player_index[qbn] = (code, "qb")
        for p in skills:
            name = str(p.get("player") or "").strip()
            if not name or name in player_index:
                raise NflPropSimulationError("PLAYER_IDENTITY_DUPLICATE")
            player_index[name] = (code, "player")

    counts = {len(v) for v in paths.values()}
    if len(counts) != 1:
        raise NflPropSimulationError("GAME_PATH_COUNT_MISMATCH")

    out: list[dict[str, Any]] = []
    for row in markets:
        player = str(row.get("player") or "").strip()
        market = str(row.get("market") or "").strip()
        side = str(row.get("selection") or "").upper().strip()
        if player not in player_index or market not in SUPPORTED:
            raise NflPropSimulationError("PROP_IDENTITY_INVALID")
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NflPropSimulationError("PROP_LINE_INVALID") from exc
        code, kind = player_index[player]
        values: list[int] = []
        for path in paths[code]:
            draw = path["qb"] if kind == "qb" else path["players"][player]
            if market not in draw:
                raise NflPropSimulationError(f"PROP_STAT_MISSING:{market}")
            values.append(int(draw[market]))
        p, push = _price(values, line, side)
        out.append({
            "game_id": str(game_id),
            "player": player,
            "market": market,
            "selection": side,
            "line": line,
            "estimate_p": p,
            "push_p": push,
            "paths": len(values),
            "status": "RESEARCH_ONLY",
            "authority": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
        })
    return out
