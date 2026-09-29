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


def _player_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return stable market identity and the simulator's human-readable key."""
    label = str(row.get("player") or "").strip()
    if not label:
        raise NflPropSimulationError("PLAYER_IDENTITY_REQUIRED")
    stable = str(row.get("player_id") or label).strip()
    if not stable:
        raise NflPropSimulationError("PLAYER_IDENTITY_REQUIRED")
    return stable, label


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
    explicit OTHER bucket when necessary). A player may additionally carry a
    stable ``player_id``. Market rows should use that ``player_id``; legacy rows
    using ``player`` remain supported for deterministic historical fixtures.
    """
    if len(teams) != 2:
        raise NflPropSimulationError("TWO_TEAMS_REQUIRED")
    paths: dict[str, list[dict[str, Any]]] = {}
    player_index: dict[str, tuple[str, str, str, str]] = {}
    legacy_labels: dict[str, str] = {}

    def register(payload: Mapping[str, Any], code: str, kind: str) -> None:
        stable, label = _player_identity(payload)
        if stable in player_index:
            raise NflPropSimulationError("PLAYER_IDENTITY_DUPLICATE")
        if label in legacy_labels and legacy_labels[label] != stable:
            raise NflPropSimulationError("PLAYER_LABEL_DUPLICATE")
        player_index[stable] = (code, kind, label, stable)
        legacy_labels[label] = stable

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
        register(qb, code, "qb")
        for payload in skills:
            if not isinstance(payload, Mapping):
                raise NflPropSimulationError(f"TEAM_PAYLOAD_INVALID:{code}")
            register(payload, code, "player")

    counts = {len(v) for v in paths.values()}
    if len(counts) != 1:
        raise NflPropSimulationError("GAME_PATH_COUNT_MISMATCH")

    out: list[dict[str, Any]] = []
    for row in markets:
        requested_id = str(row.get("player_id") or "").strip()
        requested_label = str(row.get("player") or "").strip()
        identity = requested_id or legacy_labels.get(requested_label, "")
        market = str(row.get("market") or "").strip()
        side = str(row.get("selection") or "").upper().strip()
        if identity not in player_index or market not in SUPPORTED:
            raise NflPropSimulationError("PROP_IDENTITY_INVALID")
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NflPropSimulationError("PROP_LINE_INVALID") from exc
        code, kind, draw_name, stable = player_index[identity]
        values: list[int] = []
        for path in paths[code]:
            draw = path["qb"] if kind == "qb" else path["players"][draw_name]
            if market not in draw:
                raise NflPropSimulationError(f"PROP_STAT_MISSING:{market}")
            values.append(int(draw[market]))
        p, push = _price(values, line, side)
        out.append({
            "game_id": str(game_id),
            "player_id": stable,
            "player": draw_name,
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
