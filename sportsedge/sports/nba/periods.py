"""Coherent NBA quarter and half paths.

Quarter shares are explicit versioned model inputs. Regulation points are allocated
within each already-simulated team path so quarter sums equal regulation totals.
"""
from dataclasses import dataclass
import hashlib
import random

from .simulation import NBAGamePaths


@dataclass(frozen=True)
class NBAPeriodParameters:
    version: str
    quarter_shares: tuple[float, float, float, float]

    def validate(self) -> None:
        if not self.version:
            raise ValueError("period parameter version is required")
        if len(self.quarter_shares) != 4 or any(x <= 0 for x in self.quarter_shares):
            raise ValueError("four positive quarter shares are required")
        if abs(sum(self.quarter_shares)-1.0) > 1e-12:
            raise ValueError("quarter shares must sum to 1")


@dataclass(frozen=True)
class NBAPeriodPaths:
    home: tuple[tuple[int,int,int,int], ...]
    away: tuple[tuple[int,int,int,int], ...]
    seed: int
    parameter_version: str


def _allocate(rng: random.Random, points: int, shares: tuple[float,float,float,float]) -> tuple[int,int,int,int]:
    out=[0,0,0,0]
    cuts=(shares[0],shares[0]+shares[1],shares[0]+shares[1]+shares[2])
    for _ in range(points):
        u=rng.random()
        idx=0 if u < cuts[0] else 1 if u < cuts[1] else 2 if u < cuts[2] else 3
        out[idx]+=1
    return tuple(out)


def simulate_period_paths(game: NBAGamePaths, params: NBAPeriodParameters, *, seed: int | None=None) -> NBAPeriodPaths:
    params.validate()
    if not game.home_regulation or len(game.home_regulation) != len(game.away_regulation):
        raise ValueError("coherent regulation paths are required")
    if seed is None:
        payload=f"{game.seed}|{game.engine_version}|{params.version}|{params.quarter_shares}"
        seed=int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8],"big")
    rng=random.Random(int(seed))
    home=tuple(_allocate(rng,p,params.quarter_shares) for p in game.home_regulation)
    away=tuple(_allocate(rng,p,params.quarter_shares) for p in game.away_regulation)
    return NBAPeriodPaths(home,away,int(seed),params.version)


def quarter_margin(paths: NBAPeriodPaths, quarter: int) -> tuple[int,...]:
    if quarter not in (1,2,3,4): raise ValueError("quarter must be 1..4")
    i=quarter-1
    return tuple(h[i]-a[i] for h,a in zip(paths.home,paths.away))


def quarter_total(paths: NBAPeriodPaths, quarter: int) -> tuple[int,...]:
    if quarter not in (1,2,3,4): raise ValueError("quarter must be 1..4")
    i=quarter-1
    return tuple(h[i]+a[i] for h,a in zip(paths.home,paths.away))


def half_margin(paths: NBAPeriodPaths, half: int) -> tuple[int,...]:
    if half not in (1,2): raise ValueError("half must be 1 or 2")
    lo=0 if half==1 else 2
    return tuple(sum(h[lo:lo+2])-sum(a[lo:lo+2]) for h,a in zip(paths.home,paths.away))


def half_total(paths: NBAPeriodPaths, half: int) -> tuple[int,...]:
    if half not in (1,2): raise ValueError("half must be 1 or 2")
    lo=0 if half==1 else 2
    return tuple(sum(h[lo:lo+2])+sum(a[lo:lo+2]) for h,a in zip(paths.home,paths.away))
