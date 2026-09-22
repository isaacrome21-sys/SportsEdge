"""Deterministic coherent NBA game-score simulation foundation.

The simulator is deliberately parameter driven: fitted PIT-safe pace/efficiency and
availability models must supply the inputs. Sportsbook prices are never inputs.
One shared possession/environment shock drives both team scores so moneyline,
spread, total, and team totals can be priced from the same paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np


@dataclass(frozen=True)
class GameState:
    game_id: str
    as_of_utc: str
    model_version: str
    expected_possessions: float
    home_points_per_100: float
    away_points_per_100: float
    home_advantage_points: float = 0.0
    possession_sd: float = 4.5
    shared_efficiency_sd: float = 4.0
    team_efficiency_sd: float = 8.0


@dataclass(frozen=True)
class ScorePaths:
    home_points: np.ndarray
    away_points: np.ndarray
    seed: int


def _seed(state: GameState) -> int:
    payload = "|".join((state.game_id, state.as_of_utc, state.model_version))
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def simulate_game(state: GameState, n_paths: int = 20_000) -> ScorePaths:
    """Generate coherent final-score paths from pregame basketball state.

    This is an engine, not a fitted model. Distributional parameters must be
    estimated/calibrated chronologically before production use.
    """
    if n_paths <= 0:
        raise ValueError("n_paths must be positive")
    numeric = (
        state.expected_possessions,
        state.home_points_per_100,
        state.away_points_per_100,
        state.possession_sd,
        state.shared_efficiency_sd,
        state.team_efficiency_sd,
    )
    if not all(np.isfinite(x) for x in numeric):
        raise ValueError("NBA simulation inputs must be finite")
    if state.expected_possessions <= 0 or min(state.home_points_per_100, state.away_points_per_100) <= 0:
        raise ValueError("pace and efficiencies must be positive")
    if min(state.possession_sd, state.shared_efficiency_sd, state.team_efficiency_sd) < 0:
        raise ValueError("simulation dispersions cannot be negative")

    seed = _seed(state)
    rng = np.random.default_rng(seed)
    possessions = np.maximum(1.0, rng.normal(state.expected_possessions, state.possession_sd, n_paths))
    shared = rng.normal(0.0, state.shared_efficiency_sd, n_paths)
    home_specific = rng.normal(0.0, state.team_efficiency_sd, n_paths)
    away_specific = rng.normal(0.0, state.team_efficiency_sd, n_paths)

    home_rate = np.maximum(1.0, state.home_points_per_100 + shared + home_specific)
    away_rate = np.maximum(1.0, state.away_points_per_100 + shared + away_specific)
    home_mean = possessions * home_rate / 100.0 + state.home_advantage_points
    away_mean = possessions * away_rate / 100.0

    # Conditional Poisson scoring keeps paths integer-valued while the shared
    # possession/environment terms preserve game-level dependence.
    home = rng.poisson(np.maximum(0.01, home_mean)).astype(np.int16)
    away = rng.poisson(np.maximum(0.01, away_mean)).astype(np.int16)
    return ScorePaths(home_points=home, away_points=away, seed=seed)
