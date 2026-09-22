"""PIT-safe NHL player role and coherent shot-path foundation.

This slice supports genuine player-shot probabilities only when callers supply
versioned PIT-safe role/workload parameters. Goal/point props remain unsupported
until event attribution is modeled on the same game paths.
"""
from dataclasses import dataclass
import hashlib
import math
import random
from .simulation import NHLGamePaths


@dataclass(frozen=True)
class NHLPlayerRole:
    player_id: str
    team: str
    captured_at: str
    source: str
    version: str
    projected_toi_minutes: float
    projected_pp_toi_minutes: float
    shots_per_60: float
    pp_shots_per_60: float
    lineup_status: str

    def validate(self) -> None:
        if not all((self.player_id, self.team, self.captured_at, self.source, self.version)):
            raise ValueError("player/team/provenance/version are required")
        if self.lineup_status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("lineup status must be CONFIRMED or PROJECTED")
        vals=(self.projected_toi_minutes,self.projected_pp_toi_minutes,self.shots_per_60,self.pp_shots_per_60)
        if any(not math.isfinite(v) or v < 0 for v in vals):
            raise ValueError("workload/rates must be finite and non-negative")
        if self.projected_pp_toi_minutes > self.projected_toi_minutes:
            raise ValueError("PP TOI cannot exceed total TOI")


@dataclass(frozen=True)
class NHLPlayerShotPaths:
    player_id: str
    shots: tuple[int, ...]
    seed: int
    role_version: str


def _poisson(rng: random.Random, lam: float) -> int:
    if lam == 0: return 0
    limit=math.exp(-lam); product=1.0; count=0
    while product > limit:
        count += 1; product *= rng.random()
    return count-1


def simulate_player_shots(game: NHLGamePaths, role: NHLPlayerRole, *, seed: int | None=None) -> NHLPlayerShotPaths:
    role.validate()
    n=game.simulations
    if n <= 0: raise ValueError("game paths required")
    even_toi=max(0.0, role.projected_toi_minutes-role.projected_pp_toi_minutes)
    lam=even_toi*role.shots_per_60/60.0 + role.projected_pp_toi_minutes*role.pp_shots_per_60/60.0
    if seed is None:
        payload=f"{game.seed}|{game.engine_version}|{role.player_id}|{role.version}|{lam:.12g}"
        seed=int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8],"big")
    rng=random.Random(int(seed))
    return NHLPlayerShotPaths(role.player_id, tuple(_poisson(rng,lam) for _ in range(n)), int(seed), role.version)


def shots_over(paths: NHLPlayerShotPaths, line: float) -> tuple[float,float,float]:
    if not math.isfinite(line): raise ValueError("line must be finite")
    n=len(paths.shots)
    if n == 0: raise ValueError("shot paths required")
    values=[x-line for x in paths.shots]
    w=sum(x>0 for x in values); p=sum(x==0 for x in values)
    return w/n,p/n,(n-w-p)/n
