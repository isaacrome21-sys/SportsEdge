"""Versioned NHL team shots-on-goal path generator.

This is a distribution engine, not a fitted model. Callers must provide explicit,
versioned expected-SOG parameters learned from PIT-safe history. The generator
uses no sportsbook inputs and invents no dispersion parameter.
"""
from dataclasses import dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class NHLTeamShotParameters:
    version: str
    home_expected_sog: float
    away_expected_sog: float

    def validate(self) -> None:
        if not self.version:
            raise ValueError("team shot parameter version is required")
        for value in (self.home_expected_sog, self.away_expected_sog):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("expected SOG must be finite and positive")


@dataclass(frozen=True)
class NHLTeamShotPaths:
    home: tuple[int, ...]
    away: tuple[int, ...]
    seed: int
    parameter_version: str


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth is deterministic across our supported Python runtime and adequate for
    # hockey-scale SOG means; no unvalidated over-dispersion is introduced.
    limit = math.exp(-lam)
    k = 0
    product = 1.0
    while product > limit:
        k += 1
        product *= rng.random()
    return k - 1


def simulate_team_shot_paths(game_id: str, params: NHLTeamShotParameters, *, simulations: int = 20_000, seed: int | None = None) -> NHLTeamShotPaths:
    params.validate()
    if not game_id:
        raise ValueError("game_id is required")
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if seed is None:
        payload = f"{game_id}|{params.version}|{params.home_expected_sog:.12g}|{params.away_expected_sog:.12g}|team-sog-v1"
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    home = tuple(_poisson(rng, params.home_expected_sog) for _ in range(simulations))
    away = tuple(_poisson(rng, params.away_expected_sog) for _ in range(simulations))
    return NHLTeamShotPaths(home, away, int(seed), params.version)
