"""Deterministic shared-path NHL goal simulation foundation.

This module is deliberately parameter-driven: fitted PIT-safe team/goalie models must
supply the regulation scoring rates.  It does not infer rates from sportsbook lines.
"""

from dataclasses import dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class NHLGameState:
    game_id: str
    home_regulation_goals: float
    away_regulation_goals: float
    home_ot_win_probability: float = 0.5

    def validate(self) -> None:
        if not self.game_id:
            raise ValueError("game_id is required for deterministic provenance")
        for name, value in (
            ("home_regulation_goals", self.home_regulation_goals),
            ("away_regulation_goals", self.away_regulation_goals),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0.0 <= self.home_ot_win_probability <= 1.0:
            raise ValueError("home_ot_win_probability must be in [0, 1]")


@dataclass(frozen=True)
class NHLGamePaths:
    home_regulation: tuple[int, ...]
    away_regulation: tuple[int, ...]
    home_final: tuple[int, ...]
    away_final: tuple[int, ...]
    seed: int
    engine_version: str = "NHL_SHARED_GOALS_V1"

    @property
    def simulations(self) -> int:
        return len(self.home_final)



def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth Poisson sampler; hockey regulation rates are small."""
    if lam == 0:
        return 0
    limit = math.exp(-lam)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1



def deterministic_seed(state: NHLGameState, model_version: str = "") -> int:
    payload = (
        f"{state.game_id}|{state.home_regulation_goals:.12g}|"
        f"{state.away_regulation_goals:.12g}|{state.home_ot_win_probability:.12g}|{model_version}"
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")



def simulate_game_paths(
    state: NHLGameState,
    *,
    simulations: int = 20_000,
    seed: int | None = None,
    model_version: str = "",
) -> NHLGamePaths:
    """Generate coherent regulation and final-score paths.

    Tied regulation paths receive exactly one deciding OT/SO goal, so final moneyline,
    puck-line and total derivatives can all be evaluated from the same paths.
    """
    state.validate()
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    resolved_seed = deterministic_seed(state, model_version) if seed is None else int(seed)
    rng = random.Random(resolved_seed)
    hr: list[int] = []
    ar: list[int] = []
    hf: list[int] = []
    af: list[int] = []
    for _ in range(simulations):
        home = _poisson(rng, state.home_regulation_goals)
        away = _poisson(rng, state.away_regulation_goals)
        hr.append(home)
        ar.append(away)
        final_home, final_away = home, away
        if home == away:
            if rng.random() < state.home_ot_win_probability:
                final_home += 1
            else:
                final_away += 1
        hf.append(final_home)
        af.append(final_away)
    return NHLGamePaths(tuple(hr), tuple(ar), tuple(hf), tuple(af), resolved_seed)
