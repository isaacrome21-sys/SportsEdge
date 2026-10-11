"""Empirical research pricer for NFL player props from verified prior game logs.

Uses only the player's own historical box-score outcomes. No league prior,
no Next Gen tracking, no odds as input. Research only. Requires at least 5
prior games. Integer lines support push mass.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

NFL_PLAYER_MARKETS = frozenset({
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_YARDS", "PLAYER_PASS_TDS",
    "PLAYER_PASSING_TDS", "PLAYER_PASS_ATTEMPTS", "PLAYER_COMPLETIONS",
    "PLAYER_INTERCEPTIONS", "PLAYER_RUSHING_YARDS", "PLAYER_RUSH_YARDS",
    "PLAYER_RUSH_ATTEMPTS", "PLAYER_RECEIVING_YARDS", "PLAYER_REC_YARDS",
    "PLAYER_RECEPTIONS", "PLAYER_RUSH_PLUS_REC_YARDS",
    "PLAYER_PASS_PLUS_RUSH_YARDS",
})
_FIELD = {
    "PLAYER_PASSING_YARDS": "passing_yards",
    "PLAYER_PASS_YARDS": "passing_yards",
    "PLAYER_PASS_TDS": "passing_tds",
    "PLAYER_PASSING_TDS": "passing_tds",
    "PLAYER_PASS_ATTEMPTS": "pass_attempts",
    "PLAYER_COMPLETIONS": "completions",
    "PLAYER_INTERCEPTIONS": "interceptions",
    "PLAYER_RUSHING_YARDS": "rushing_yards",
    "PLAYER_RUSH_YARDS": "rushing_yards",
    "PLAYER_RUSH_ATTEMPTS": "rush_attempts",
    "PLAYER_RECEIVING_YARDS": "receiving_yards",
    "PLAYER_REC_YARDS": "receiving_yards",
    "PLAYER_RECEPTIONS": "receptions",
    "PLAYER_RUSH_PLUS_REC_YARDS": "rush_plus_receiving_yards",
    "PLAYER_PASS_PLUS_RUSH_YARDS": "pass_plus_rush_yards",
}


class NFLEmpiricalError(ValueError):
    pass


# Count fields that cannot be negative in a verified box score. Yardage
# fields are intentionally excluded: real rushing/receiving lines can be
# negative (e.g. losses on carries), and rejecting them would fail-closed
# on legitimate verified history.
_NONNEGATIVE_FIELDS = frozenset({
    "passing_tds", "pass_attempts", "completions", "interceptions",
    "rush_attempts", "receptions",
})


def price_nfl_player_market(
    *, market: str, side: str, line: float,
    game_history: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return model_p and push_p from the player's own prior games."""
    m = str(market).upper()
    if m not in NFL_PLAYER_MARKETS:
        raise NFLEmpiricalError(f"UNSUPPORTED_NFL_PLAYER_MARKET:{m}")
    s = str(side).upper()
    if s not in {"OVER", "UNDER"}:
        raise NFLEmpiricalError("SIDE_MUST_BE_OVER_UNDER")
    if not isfinite(float(line)):
        raise NFLEmpiricalError("LINE_NONFINITE")
    field = _FIELD[m]
    values = []
    for i, row in enumerate(game_history):
        if not isinstance(row, Mapping):
            raise NFLEmpiricalError(f"GAME_HISTORY[{i}]_NOT_OBJECT")
        raw = row.get(field)
        if raw is None:
            # Derived fields
            if field == "rush_plus_receiving_yards":
                raw = (row.get("rushing_yards") or 0) + (row.get("receiving_yards") or 0)
            elif field == "pass_plus_rush_yards":
                raw = (row.get("passing_yards") or 0) + (row.get("rushing_yards") or 0)
            else:
                raise NFLEmpiricalError(f"GAME_HISTORY[{i}].{field}_MISSING")
        try:
            v = float(raw)
        except (TypeError, ValueError) as exc:
            raise NFLEmpiricalError(f"GAME_HISTORY[{i}].{field}_INVALID") from exc
        if field in _NONNEGATIVE_FIELDS and v < 0:
            raise NFLEmpiricalError(f"GAME_HISTORY[{i}].{field}_NEGATIVE")
        values.append(v)
    if len(values) < 5:
        raise NFLEmpiricalError("FEWER_THAN_FIVE_PRIOR_GAMES")
    n = len(values)
    threshold = float(line)
    over = sum(v > threshold for v in values) / n
    under = sum(v < threshold for v in values) / n
    push = sum(abs(v - threshold) < 1e-9 for v in values) / n if threshold.is_integer() else 0.0
    if abs(over + under + push - 1.0) > 1e-9:
        raise NFLEmpiricalError("PROBABILITY_MASS_NOT_CONSERVED")
    p = over if s == "OVER" else under
    return {
        "model_p": float(p),
        "push_p": float(push),
        "effective_history_games": n,
        "engine": "nfl_player_empirical_gamelog_v1",
    }
