"""Exact-line NFL game probabilities from shared simulation paths.

This prevents a probability generated for one spread/total threshold from being
silently reused at another threshold.  Every requested line is evaluated against
the empirical score distribution from the supplied game paths.

Research / impulse presentation only. No OFFICIAL, Truth-Gate or staking authority.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from sportsedge.sports.nfl.sgp_joint_probability import (
    NFLJointProbabilityError,
    evaluate_leg,
)


GAME_PATH_PROB_SCHEMA = "NFL_GAME_PATH_PROBABILITY_V1"
_SUPPORTED = {"MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL"}


class NFLGamePathProbabilityError(ValueError):
    pass


def _market(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "ML": "MONEYLINE",
        "MONEY_LINE": "MONEYLINE",
        "GAME_SPREAD": "SPREAD",
        "GAME_TOTAL": "TOTAL",
        "TOTAL_POINTS": "TOTAL",
        "TEAM_TOTAL_POINTS": "TEAM_TOTAL",
    }
    return aliases.get(raw, raw)


def probability_for_game_leg(
    simulation_paths: Iterable[Mapping[str, Any]],
    leg: Mapping[str, Any],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Evaluate one exact sportsbook game leg over all supplied score paths."""
    market = _market(leg.get("market"))
    if market not in _SUPPORTED:
        raise NFLGamePathProbabilityError(f"NFL_GAME_PATH_MARKET_UNSUPPORTED:{market}")

    paths = [dict(path) for path in simulation_paths]
    if not paths:
        raise NFLGamePathProbabilityError("NFL_GAME_PATHS_REQUIRED")

    counts = {"WIN": 0, "LOSS": 0, "PUSH": 0, "UNRESOLVED": 0}
    observed_game_ids: set[str] = set()
    requested_game = str(leg.get("game_id") or "").strip()

    for path in paths:
        path_game = str(path.get("game_id") or "").strip()
        if path_game:
            observed_game_ids.add(path_game)
        if requested_game and path_game and path_game != requested_game:
            counts["UNRESOLVED"] += 1
            if strict:
                raise NFLGamePathProbabilityError("NFL_GAME_PATH_GAME_ID_MISMATCH")
            continue
        try:
            result = evaluate_leg(path, leg)
        except NFLJointProbabilityError as exc:
            raise NFLGamePathProbabilityError(str(exc)) from exc
        counts[result.result] += 1
        if result.result == "UNRESOLVED" and strict:
            raise NFLGamePathProbabilityError(
                "NFL_GAME_PATH_UNRESOLVED:" + str(result.reason or "UNKNOWN")
            )

    resolved = counts["WIN"] + counts["LOSS"] + counts["PUSH"]
    if resolved <= 0:
        raise NFLGamePathProbabilityError("NFL_GAME_PATH_NO_RESOLVED_PATHS")
    decision = counts["WIN"] + counts["LOSS"]
    conditional_win = None if decision == 0 else counts["WIN"] / decision

    return {
        "schema_version": GAME_PATH_PROB_SCHEMA,
        "method": "EXACT_LINE_SHARED_SCORE_PATHS",
        "game_id": requested_game or (next(iter(observed_game_ids)) if len(observed_game_ids) == 1 else None),
        "market": market,
        "team": leg.get("team"),
        "side": leg.get("side"),
        "line": leg.get("line"),
        "estimate_p": counts["WIN"] / resolved,
        "conditional_win_probability_ex_push": conditional_win,
        "push_probability": counts["PUSH"] / resolved,
        "loss_probability": counts["LOSS"] / resolved,
        "win_paths": counts["WIN"],
        "loss_paths": counts["LOSS"],
        "push_paths": counts["PUSH"],
        "unresolved_paths": counts["UNRESOLVED"],
        "resolved_paths": resolved,
        "total_paths": len(paths),
        "resolved_fraction": resolved / len(paths),
        "exact_line_required": True,
        "authority": "RESEARCH_IMPULSE_ONLY",
    }


def build_game_market_board(
    simulation_paths: Iterable[Mapping[str, Any]],
    legs: Sequence[Mapping[str, Any]],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Evaluate a set of exact game lines on one common simulation population."""
    paths = [dict(path) for path in simulation_paths]
    if not paths:
        raise NFLGamePathProbabilityError("NFL_GAME_PATHS_REQUIRED")
    rows = [probability_for_game_leg(paths, leg, strict=strict) for leg in legs]
    return {
        "schema_version": GAME_PATH_PROB_SCHEMA,
        "sport": "NFL",
        "method": "EXACT_LINE_SHARED_SCORE_PATHS",
        "rows": rows,
        "path_count": len(paths),
        "authority": "RESEARCH_IMPULSE_ONLY",
    }
