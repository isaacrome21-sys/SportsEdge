"""Empirical research pricer for MLB batter props from verified prior game logs.

Uses only the player's own historical plate-appearance outcomes. No league
Poisson prior, no Statcast (not yet wired), no odds as input. Research only.
Requires at least 10 prior games. Integer lines support push mass.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

BATTER_MARKETS = frozenset({
    "BATTER_HITS", "BATTER_TOTAL_BASES", "BATTER_RBIS", "BATTER_RUNS",
    "BATTER_HRS", "BATTER_HOME_RUNS", "BATTER_STOLEN_BASES",
    "BATTER_BB", "BATTER_WALKS", "BATTER_K", "BATTER_STRIKEOUTS",
    "BATTER_SINGLES", "SINGLES", "BATTER_DOUBLES", "DOUBLES",
    "HITS_RUNS_RBIS", "H_R_RBI",
})
_FIELD = {
    "BATTER_HITS": "hits",
    "BATTER_TOTAL_BASES": "total_bases",
    "BATTER_RBIS": "rbi",
    "BATTER_RUNS": "runs",
    "BATTER_HRS": "home_runs",
    "BATTER_HOME_RUNS": "home_runs",
    "BATTER_STOLEN_BASES": "stolen_bases",
    "BATTER_BB": "walks", "BATTER_WALKS": "walks",
    "BATTER_K": "strikeouts", "BATTER_STRIKEOUTS": "strikeouts",
    "BATTER_SINGLES": "singles", "SINGLES": "singles",
    "BATTER_DOUBLES": "doubles", "DOUBLES": "doubles",
    "HITS_RUNS_RBIS": "hits_runs_rbis", "H_R_RBI": "hits_runs_rbis",
}


class BatterEmpiricalError(ValueError):
    pass


def price_batter_market(
    *, market: str, side: str, line: float,
    pa_history: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return model_p and push_p from the player's own prior games."""
    m = str(market).upper()
    if m not in BATTER_MARKETS:
        raise BatterEmpiricalError(f"UNSUPPORTED_BATTER_MARKET:{m}")
    s = str(side).upper()
    if s not in {"OVER", "UNDER"}:
        raise BatterEmpiricalError("SIDE_MUST_BE_OVER_UNDER")
    if not isfinite(float(line)):
        raise BatterEmpiricalError("LINE_NONFINITE")
    field = _FIELD[m]
    values = []
    for i, row in enumerate(pa_history):
        if not isinstance(row, Mapping):
            raise BatterEmpiricalError(f"PA_HISTORY[{i}]_NOT_OBJECT")
        raw = row.get(field)
        try:
            v = int(raw)
        except (TypeError, ValueError) as exc:
            raise BatterEmpiricalError(f"PA_HISTORY[{i}].{field}_INVALID") from exc
        if v < 0:
            raise BatterEmpiricalError(f"PA_HISTORY[{i}].{field}_NEGATIVE")
        values.append(v)
    if len(values) < 10:
        raise BatterEmpiricalError("FEWER_THAN_TEN_PRIOR_GAMES")
    n = len(values)
    threshold = float(line)
    over = sum(v > threshold for v in values) / n
    under = sum(v < threshold for v in values) / n
    push = sum(v == threshold for v in values) / n if threshold.is_integer() else 0.0
    if abs(over + under + push - 1.0) > 1e-9:
        raise BatterEmpiricalError("PROBABILITY_MASS_NOT_CONSERVED")
    p = over if s == "OVER" else under
    return {
        "model_p": float(p),
        "push_p": float(push),
        "effective_history_games": n,
        "engine": "mlb_batter_empirical_game_log_v1",
    }
