"""Empirical research pricer for MLB batter props from verified prior game logs.

Uses only the player's own historical plate-appearance outcomes. No league
Poisson prior, no Statcast (not yet wired), no odds as input. Research only.
Requires at least 10 prior games. Integer lines support push mass.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

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
    "BATTER_TRIPLES": "triples", "TRIPLES": "triples",
    "HITS_RUNS_RBIS": "hits_runs_rbis", "H_R_RBI": "hits_runs_rbis",
}
# Derived markets: exact per-game arithmetic over measured component
# fields the public history source already collects (deployments.json:
# EXTRA_BASE_HITS is the "exact marginal of doubles+triples+home runs
# from same prior-game rows"; RUNS_RBIS is "exact arithmetic on same
# prior-game rows"). A game missing any component fails the market
# closed; components are never zero-filled.
_DERIVED = {
    "BATTER_EXTRA_BASE_HITS": ("doubles", "triples", "home_runs"),
    "EXTRA_BASE_HITS": ("doubles", "triples", "home_runs"),
    "BATTER_RUNS_RBIS": ("runs", "rbi"),
    "RUNS_RBIS": ("runs", "rbi"),
}
BATTER_MARKETS = frozenset(_FIELD) | frozenset(_DERIVED)


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
    values = []
    for i, row in enumerate(pa_history):
        if not isinstance(row, Mapping):
            raise BatterEmpiricalError(f"PA_HISTORY[{i}]_NOT_OBJECT")
        if m in _DERIVED:
            total = 0
            for component in _DERIVED[m]:
                raw = row.get(component)
                # An observed event count must be an exact integer.
                # int(1.9) and int(True) silently invent different data.
                if isinstance(raw, bool):
                    raise BatterEmpiricalError(
                        f"PA_HISTORY[{i}].{component}_INVALID")
                try:
                    v = int(raw)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise BatterEmpiricalError(
                        f"PA_HISTORY[{i}].{component}_INVALID") from exc
                if not isinstance(raw, (int, str)) or str(v) != str(raw).strip():
                    raise BatterEmpiricalError(
                        f"PA_HISTORY[{i}].{component}_NONINTEGER")
                if v < 0:
                    raise BatterEmpiricalError(
                        f"PA_HISTORY[{i}].{component}_NEGATIVE")
                total += v
            values.append(total)
            continue
        field = _FIELD[m]
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
