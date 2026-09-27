"""Deterministic NHL period paths derived from regulation scoring rates.

Period shares are explicit versioned model inputs. No empirical share or fitted
performance is claimed here. Period paths sum exactly to each regulation path so
period derivatives remain coherent with the game simulation.
"""
from dataclasses import dataclass
import hashlib
import random

from .simulation import NHLGamePaths


@dataclass(frozen=True)
class NHLPeriodParameters:
    version: str
    shares: tuple[float, float, float]

    def validate(self) -> None:
        if not self.version:
            raise ValueError("period parameter version is required")
        if len(self.shares) != 3 or any(x <= 0 for x in self.shares):
            raise ValueError("three positive period shares are required")
        if abs(sum(self.shares) - 1.0) > 1e-12:
            raise ValueError("period shares must sum to 1")


@dataclass(frozen=True)
class NHLPeriodPaths:
    home: tuple[tuple[int, int, int], ...]
    away: tuple[tuple[int, int, int], ...]
    seed: int
    parameter_version: str


def _allocate(rng: random.Random, goals: int, shares: tuple[float, float, float]) -> tuple[int, int, int]:
    out = [0, 0, 0]
    cut1, cut2 = shares[0], shares[0] + shares[1]
    for _ in range(goals):
        u = rng.random()
        out[0 if u < cut1 else 1 if u < cut2 else 2] += 1
    return tuple(out)


def simulate_period_paths(game: NHLGamePaths, params: NHLPeriodParameters, *, seed: int | None = None) -> NHLPeriodPaths:
    params.validate()
    if not game.home_regulation or len(game.home_regulation) != len(game.away_regulation):
        raise ValueError("coherent regulation paths are required")
    if seed is None:
        payload = f"{game.seed}|{game.engine_version}|{params.version}|{params.shares}"
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    home = tuple(_allocate(rng, goals, params.shares) for goals in game.home_regulation)
    away = tuple(_allocate(rng, goals, params.shares) for goals in game.away_regulation)
    return NHLPeriodPaths(home, away, int(seed), params.version)


def period_three_way(paths: NHLPeriodPaths, period: int) -> tuple[float, float, float]:
    if period not in (1, 2, 3):
        raise ValueError("period must be 1, 2, or 3")
    idx = period - 1
    n = len(paths.home)
    if n == 0 or len(paths.away) != n:
        raise ValueError("period paths are required")
    h = sum(a[idx] > b[idx] for a, b in zip(paths.home, paths.away))
    d = sum(a[idx] == b[idx] for a, b in zip(paths.home, paths.away))
    return h / n, d / n, (n - h - d) / n


def period_total_over(paths: NHLPeriodPaths, period: int, line: float) -> tuple[float, float, float]:
    if period not in (1, 2, 3):
        raise ValueError("period must be 1, 2, or 3")
    idx = period - 1
    values = [h[idx] + a[idx] - line for h, a in zip(paths.home, paths.away)]
    n = len(values)
    if n == 0:
        raise ValueError("period paths are required")
    wins = sum(v > 0 for v in values); pushes = sum(v == 0 for v in values)
    return wins / n, pushes / n, (n - wins - pushes) / n
