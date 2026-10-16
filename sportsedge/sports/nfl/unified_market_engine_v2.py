"""NFL unified research market engine — V2 safety re-lock (owner t212u, #2265).

A separately versioned forward identity. It does NOT replace or edit the frozen
V1 engine (``unified_market_engine.py`` and the six other V1 forward-lock files
stay byte-identical). V2 validates complete probability mass on every score
grid before any direct sampling or pricing and refuses malformed grids
(non-numeric, non-finite, negative, empty, or mass off 1 beyond
``MASS_TOLERANCE``). It never renormalizes and never relies on V1's
``cumulative[-1] = 1.0`` masking: an invalid grid never reaches V1 code.

V2 has no forward evidence. Evidence may start only after a new owner-approved
freeze; nothing here freezes V2 or alters any V1 forward record.
Research only: no Truth-Gate, OFFICIAL, promotion, or staking authority.
"""
from __future__ import annotations

from math import fsum, isfinite
from numbers import Real
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl import unified_market_engine as _v1
from sportsedge.sports.nfl.discrete_v2 import load_freeze, means_from_attempt9, score_grid

TD_PROP_MARKETS = _v1.TD_PROP_MARKETS
UnifiedNflModelError = _v1.UnifiedNflModelError

SCHEMA = "SPORTSEDGE_NFL_UNIFIED_RESEARCH_MARKET_ENGINE_V2"
MASS_TOLERANCE = 1e-9
FORWARD_IDENTITY: dict[str, Any] = {
    "engine_version": "NFL_UNIFIED_MARKET_ENGINE_V2",
    "schema": SCHEMA,
    "v1_schema": _v1.SCHEMA,
    "replaces_v1": False,
    "frozen": False,
    "forward_evidence_status": "NO_EVIDENCE_UNTIL_NEW_APPROVED_FREEZE",
    "grid_contract": "COMPLETE_MASS_VALIDATED_NO_RENORMALIZATION",
    "mass_tolerance": MASS_TOLERANCE,
}


class UnifiedNflV2GridError(_v1.UnifiedNflModelError):
    pass


def validate_score_grid(grid: Sequence[Sequence[Any]]) -> None:
    """Refuse a malformed joint score grid. Never mutates or rescales it."""
    if not isinstance(grid, Sequence) or isinstance(grid, (str, bytes)):
        raise UnifiedNflV2GridError("SCORE_GRID_NONNUMERIC")
    values: list[float] = []
    for row in grid:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise UnifiedNflV2GridError("SCORE_GRID_NONNUMERIC")
        for value in row:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise UnifiedNflV2GridError("SCORE_GRID_NONNUMERIC")
            p = float(value)
            if not isfinite(p):
                raise UnifiedNflV2GridError("SCORE_GRID_NONFINITE")
            if p < 0.0:
                raise UnifiedNflV2GridError("SCORE_GRID_NEGATIVE")
            values.append(p)
    mass = fsum(values)
    if not values or mass <= 0.0:
        raise UnifiedNflV2GridError("SCORE_GRID_EMPTY")
    if abs(mass - 1.0) > MASS_TOLERANCE:
        raise UnifiedNflV2GridError(f"SCORE_GRID_MASS_NOT_ONE:{mass!r}")


def guarded_score_grid(mean_home: float, mean_away: float, freeze: Any = None) -> list[list[float]]:
    grid = score_grid(mean_home, mean_away, freeze if freeze is not None else load_freeze())
    validate_score_grid(grid)
    return grid


def sample_score_paths(grid: Sequence[Sequence[float]], *, n_sims: int, seed: int) -> list[dict[str, Any]]:
    validate_score_grid(grid)
    return _v1.sample_score_paths(grid, n_sims=n_sims, seed=seed)


def price_game_market(grid: Sequence[Sequence[float]], request: Mapping[str, Any]) -> dict[str, Any]:
    validate_score_grid(grid)
    return _v1.price_game_market(grid, request)


def _validate_location(attempt9_margin: Any, attempt9_total: Any) -> None:
    margin = _v1._num(attempt9_margin, "attempt9_margin")
    total = _v1._num(attempt9_total, "attempt9_total")
    if total <= 0:
        raise _v1.UnifiedNflModelError("ATTEMPT9_TOTAL_POSITIVE_REQUIRED")
    means = means_from_attempt9(margin, total)
    validate_score_grid(score_grid(means["mean_home"], means["mean_away"], load_freeze()))


def run_unified_nfl_model(**kwargs: Any) -> dict[str, Any]:
    """Validate the exact grid V1 will build, then run V1 unchanged.

    The frozen grid is deterministic in (margin, total, freeze), so the grid V1
    samples internally is the grid validated here.
    """
    _validate_location(kwargs.get("attempt9_margin"), kwargs.get("attempt9_total"))
    out = _v1.run_unified_nfl_model(**kwargs)
    out["engine_identity"] = dict(FORWARD_IDENTITY)
    return out


def _v1_run_unified_nfl_run_it(**kwargs: Any) -> dict[str, Any]:
    from sportsedge.sports.nfl.unified_run_it import run_unified_nfl_run_it
    return run_unified_nfl_run_it(**kwargs)


def run_unified_nfl_run_it(**kwargs: Any) -> dict[str, Any]:
    """V2 entry for RUN IT: guards the frozen unified_run_it.py:334 re-sample."""
    _validate_location(kwargs.get("attempt9_margin"), kwargs.get("attempt9_total"))
    out = _v1_run_unified_nfl_run_it(**kwargs)
    if isinstance(out, dict):
        out["engine_identity"] = dict(FORWARD_IDENTITY)
    return out


__all__ = [
    "FORWARD_IDENTITY", "TD_PROP_MARKETS", "UnifiedNflModelError", "MASS_TOLERANCE", "SCHEMA", "UnifiedNflV2GridError",
    "guarded_score_grid", "price_game_market", "run_unified_nfl_model",
    "run_unified_nfl_run_it", "sample_score_paths", "validate_score_grid",
]
