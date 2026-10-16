"""Fail-closed integrity checks for NFL research joint-score grids.

Validation is shape/mass integrity only, not predictive calibration or
market-price verification. Does not grant a model or betting authorization.
"""
from __future__ import annotations

from math import fsum, isfinite
from numbers import Real
from typing import Any, Sequence

MASS_TOLERANCE = 1e-8


class ScoreGridIntegrityError(ValueError):
    """Named refusal for malformed score-path probability mass."""


def validate_score_grid(grid: Any) -> None:
    """Validate a normalized rectangular home-score x away-score grid.

    No implicit normalization: missing/excess probability mass is a defect,
    not something a downstream sampler may conceal by rewriting its CDF.
    """
    if not isinstance(grid, Sequence) or isinstance(grid, (str, bytes, bytearray)) or not grid:
        raise ScoreGridIntegrityError("SCORE_GRID_EMPTY_OR_INVALID")
    width = None
    probabilities = []
    for row in grid:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray)) or not row:
            raise ScoreGridIntegrityError("SCORE_GRID_ROW_INVALID")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ScoreGridIntegrityError("SCORE_GRID_RAGGED")
        for probability in row:
            if isinstance(probability, bool) or not isinstance(probability, Real):
                raise ScoreGridIntegrityError("SCORE_GRID_NONNUMERIC")
            p = float(probability)
            if not isfinite(p):
                raise ScoreGridIntegrityError("SCORE_GRID_NONFINITE")
            if p < 0.0:
                raise ScoreGridIntegrityError("SCORE_GRID_NEGATIVE")
            if p > 1.0:
                raise ScoreGridIntegrityError("SCORE_GRID_CELL_ABOVE_ONE")
            probabilities.append(p)
    if abs(fsum(probabilities) - 1.0) > MASS_TOLERANCE:
        raise ScoreGridIntegrityError("SCORE_GRID_MASS_NOT_ONE")
