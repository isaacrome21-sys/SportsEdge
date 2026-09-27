"""Deterministic NBA player-stat paths tied to shared game simulations.

Role parameters are versioned PIT-safe model inputs. This module does not fit or
invent them from sportsbook prices. Points are bounded by the player's team score;
minutes and shared game pace drive rebounds/assists/threes on the same path so
combo props are derived from joint simulations rather than independent marginals.
"""
from dataclasses import dataclass
import hashlib
import math
import random

from .simulation import NBAGamePaths


@dataclass(frozen=True)
class NBAPlayerStatRole:
    player_id: str
    team: str
    version: str
    minutes_mean: float
    minutes_sd: float
    point_share: float
    rebounds_per_minute: float
    assists_per_minute: float
    threes_per_minute: float

    def validate(self) -> None:
        if not self.player_id or not self.version:
            raise ValueError("player_id/version are required")
        if self.team not in {"HOME", "AWAY"}:
            raise ValueError("team must be HOME or AWAY")
        vals=(self.minutes_mean,self.minutes_sd,self.point_share,self.rebounds_per_minute,self.assists_per_minute,self.threes_per_minute)
        if any(not math.isfinite(v) or v < 0 for v in vals):
            raise ValueError("player-stat role inputs must be finite and non-negative")
        if self.minutes_mean > 48 or self.point_share > 1:
            raise ValueError("minutes_mean <= 48 and point_share <= 1 are required")


@dataclass(frozen=True)
class NBAPlayerStatPaths:
    player_id: str
    minutes: tuple[float, ...]
    points: tuple[int, ...]
    rebounds: tuple[int, ...]
    assists: tuple[int, ...]
    threes: tuple[int, ...]
    seed: int
    role_version: str

    @property
    def pra(self) -> tuple[int, ...]:
        return tuple(p+r+a for p,r,a in zip(self.points,self.rebounds,self.assists))

    @property
    def pr(self) -> tuple[int, ...]:
        return tuple(p+r for p,r in zip(self.points,self.rebounds))

    @property
    def pa(self) -> tuple[int, ...]:
        return tuple(p+a for p,a in zip(self.points,self.assists))

    @property
    def ra(self) -> tuple[int, ...]:
        return tuple(r+a for r,a in zip(self.rebounds,self.assists))


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0: return 0
    limit=math.exp(-lam); product=1.0; count=0
    while product > limit:
        count += 1; product *= rng.random()
    return count-1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(rng.random() < p for _ in range(n))


def simulate_player_stats(game: NBAGamePaths, role: NBAPlayerStatRole, *, seed: int | None=None) -> NBAPlayerStatPaths:
    role.validate()
    team_points=game.home_regulation if role.team == "HOME" else game.away_regulation
    if not team_points or len(team_points) != len(game.possessions):
        raise ValueError("coherent game paths are required")
    if seed is None:
        payload=f"{game.seed}|{game.engine_version}|{role.player_id}|{role.version}|player-stats-v1"
        seed=int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8],"big")
    rng=random.Random(int(seed))
    mins=[]; pts=[]; rebs=[]; asts=[]; threes=[]
    baseline=sum(game.possessions)/len(game.possessions)
    for possessions, team_total in zip(game.possessions,team_points):
        m=min(48.0,max(0.0,rng.gauss(role.minutes_mean,role.minutes_sd)))
        pace_factor=possessions/baseline
        p=_binomial(rng,team_total,role.point_share)
        r=_poisson(rng,role.rebounds_per_minute*m*pace_factor)
        a=_poisson(rng,role.assists_per_minute*m*pace_factor)
        # A made three consumes at least three player points; cap accordingly.
        t=min(p//3,_poisson(rng,role.threes_per_minute*m*pace_factor))
        mins.append(m); pts.append(p); rebs.append(r); asts.append(a); threes.append(t)
    return NBAPlayerStatPaths(role.player_id,tuple(mins),tuple(pts),tuple(rebs),tuple(asts),tuple(threes),int(seed),role.version)
