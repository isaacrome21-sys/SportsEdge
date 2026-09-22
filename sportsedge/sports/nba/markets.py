"""NBA market probabilities derived only from coherent shared score paths.

These helpers intentionally do not fit pace/efficiency or consume sportsbook prices.
They convert one shared simulated game distribution into mutually consistent RUN IT
probabilities for the honestly supported full-game market surface.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .simulation import ScorePaths


@dataclass(frozen=True)
class OutcomeProbability:
    win: float
    push: float
    loss: float

    def __post_init__(self) -> None:
        values = (self.win, self.push, self.loss)
        if any(not math.isfinite(v) or v < 0.0 or v > 1.0 for v in values):
            raise ValueError("probability mass must be finite and in [0, 1]")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-12):
            raise ValueError("win/push/loss probability mass must sum to 1")


def _validate(paths: ScorePaths) -> int:
    n = len(paths.home_points)
    if n <= 0 or len(paths.away_points) != n:
        raise ValueError("NBA score paths must be non-empty and equal length")
    return n


def _mass(values: np.ndarray) -> OutcomeProbability:
    n = len(values)
    wins = int(np.count_nonzero(values > 0))
    pushes = int(np.count_nonzero(values == 0))
    return OutcomeProbability(wins / n, pushes / n, (n - wins - pushes) / n)


def home_moneyline(paths: ScorePaths) -> OutcomeProbability:
    """Home full-game moneyline probability, preserving simulated tie mass.

    ScorePaths currently model regulation/full-game scoring without a dedicated OT
    resolution layer, so ties remain pushes rather than being silently assigned.
    """
    _validate(paths)
    return _mass(paths.home_points.astype(np.int32) - paths.away_points.astype(np.int32))


def home_spread(paths: ScorePaths, line: float) -> OutcomeProbability:
    """Home spread W/P/L from shared score paths."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    _validate(paths)
    return _mass(paths.home_points.astype(np.float64) - paths.away_points + line)


def game_total_over(paths: ScorePaths, line: float) -> OutcomeProbability:
    """Full-game total-over W/P/L from the same paths used by side markets."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    _validate(paths)
    return _mass(paths.home_points.astype(np.float64) + paths.away_points - line)


def team_total_over(paths: ScorePaths, *, home: bool, line: float) -> OutcomeProbability:
    """Team-total over W/P/L from the coherent game distribution."""
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    _validate(paths)
    scores = paths.home_points if home else paths.away_points
    return _mass(scores.astype(np.float64) - line)
