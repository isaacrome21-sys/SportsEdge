"""Deterministic coherent NBA game simulation foundation.

Parameters must come from fitted PIT-safe NBA models. Sportsbook lines are not
used to manufacture scoring rates. All game/period derivatives share these paths.
"""
from dataclasses import dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class NBAGameState:
    game_id: str
    expected_possessions: float
    home_points_per_100: float
    away_points_per_100: float
    possession_sd: float = 6.0
    scoring_sd_per_possession: float = 1.05
    overtime_possessions: float = 10.0

    def validate(self) -> None:
        if not self.game_id:
            raise ValueError("game_id is required")
        for name, value in (
            ("expected_possessions", self.expected_possessions),
            ("home_points_per_100", self.home_points_per_100),
            ("away_points_per_100", self.away_points_per_100),
            ("possession_sd", self.possession_sd),
            ("scoring_sd_per_possession", self.scoring_sd_per_possession),
            ("overtime_possessions", self.overtime_possessions),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class NBAGamePaths:
    possessions: tuple[int, ...]
    home_regulation: tuple[int, ...]
    away_regulation: tuple[int, ...]
    home_final: tuple[int, ...]
    away_final: tuple[int, ...]
    seed: int
    engine_version: str = "NBA_SHARED_POSSESSIONS_V1"

    @property
    def simulations(self) -> int:
        return len(self.home_final)


def deterministic_seed(state: NBAGameState, model_version: str = "") -> int:
    payload = (
        f"{state.game_id}|{state.expected_possessions:.12g}|{state.home_points_per_100:.12g}|"
        f"{state.away_points_per_100:.12g}|{state.possession_sd:.12g}|"
        f"{state.scoring_sd_per_possession:.12g}|{state.overtime_possessions:.12g}|{model_version}"
    )
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")


def _score(rng: random.Random, possessions: int, efficiency: float, noise: float) -> int:
    mean = possessions * efficiency / 100.0
    sd = noise * math.sqrt(possessions)
    return max(0, int(round(rng.gauss(mean, sd))))


def simulate_game_paths(state: NBAGameState, *, simulations: int = 20_000, seed: int | None = None, model_version: str = "") -> NBAGamePaths:
    state.validate()
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    resolved = deterministic_seed(state, model_version) if seed is None else int(seed)
    rng = random.Random(resolved)
    poss=[]; hr=[]; ar=[]; hf=[]; af=[]
    for _ in range(simulations):
        p=max(1, int(round(rng.gauss(state.expected_possessions, state.possession_sd))))
        h=_score(rng,p,state.home_points_per_100,state.scoring_sd_per_possession)
        a=_score(rng,p,state.away_points_per_100,state.scoring_sd_per_possession)
        poss.append(p); hr.append(h); ar.append(a)
        fh,fa=h,a
        # NBA games cannot finish tied. Simulate repeated five-minute OT periods.
        while fh == fa:
            op=max(1,int(round(state.overtime_possessions)))
            fh += _score(rng,op,state.home_points_per_100,state.scoring_sd_per_possession)
            fa += _score(rng,op,state.away_points_per_100,state.scoring_sd_per_possession)
            # Extremely rare zero/tied OT is handled by the next period, not a coin flip.
        hf.append(fh); af.append(fa)
    return NBAGamePaths(tuple(poss),tuple(hr),tuple(ar),tuple(hf),tuple(af),resolved)
