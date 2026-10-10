"""One-pass G1 grid market statistics; research-only, no betting authority.

The caller must provide the already-validated frozen score grid. This helper
never fits a model, changes a probability, or reads a new source.
"""
from __future__ import annotations

from math import isfinite

KEY_MARGINS = (-7, -3, 3, 7)


def summarize_grid(grid, *, spread_line=None, total_line=None):
    """Return exact unrounded win/push/loss masses in one traversal.

    Spread is home handicap and total is over. Moneyline uses spread=0.
    A missing line is represented by None and never interpreted as zero.
    """
    markets = {"moneyline": [0.0, 0.0, 0.0]}
    if spread_line is not None:
        markets["spread"] = [0.0, 0.0, 0.0]
    if total_line is not None:
        markets["total"] = [0.0, 0.0, 0.0]
    key_mass = {k: 0.0 for k in KEY_MARGINS}
    total_mass = 0.0
    for home, row in enumerate(grid):
        for away, raw_p in enumerate(row):
            p = float(raw_p)
            if not isfinite(p) or p < 0:
                raise ValueError("NFL_G1_GRID_PROBABILITY_INVALID")
            total_mass += p
            margin = home - away
            total = home + away
            moneyline_i = 0 if margin > 0 else 2 if margin < 0 else 1
            markets["moneyline"][moneyline_i] += p
            if spread_line is not None:
                d = margin + spread_line
                markets["spread"][0 if d > 0 else 2 if d < 0 else 1] += p
            if total_line is not None:
                d = total - total_line
                markets["total"][0 if d > 0 else 2 if d < 0 else 1] += p
            if margin in key_mass:
                key_mass[margin] += p
    if abs(total_mass - 1.0) > 1e-9:
        raise ValueError("NFL_G1_GRID_NOT_NORMALIZED")
    return {"markets": {k: tuple(v) for k, v in markets.items()},
            "signed_key_mass": key_mass}
