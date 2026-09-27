"""Coherent NHL player goal/point event attribution.

Player event shares are explicit, versioned PIT-safe model inputs. Events are
allocated from the already-simulated team regulation goals, so player scoring
cannot exceed team scoring on any path. No fitted shares/performance are claimed.
"""
from dataclasses import dataclass
import hashlib
import math
import random
from .simulation import NHLGamePaths


@dataclass(frozen=True)
class NHLPlayerEventRole:
    player_id: str
    team: str
    captured_at: str
    source: str
    version: str
    goal_share: float
    primary_assist_share: float
    secondary_assist_share: float
    lineup_status: str

    def validate(self) -> None:
        if not all((self.player_id, self.team, self.captured_at, self.source, self.version)):
            raise ValueError("player/team/provenance/version are required")
        if self.team not in {"HOME", "AWAY"}:
            raise ValueError("team must be HOME or AWAY")
        if self.lineup_status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("lineup status must be CONFIRMED or PROJECTED")
        for value in (self.goal_share, self.primary_assist_share, self.secondary_assist_share):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("event shares must be finite and in [0, 1]")


@dataclass(frozen=True)
class NHLPlayerEventPaths:
    player_id: str
    goals: tuple[int, ...]
    assists: tuple[int, ...]
    points: tuple[int, ...]
    seed: int
    role_version: str


def simulate_player_events(game: NHLGamePaths, role: NHLPlayerEventRole, *, seed: int | None = None) -> NHLPlayerEventPaths:
    role.validate()
    team_goals = game.home_regulation if role.team == "HOME" else game.away_regulation
    if not team_goals:
        raise ValueError("game paths required")
    if seed is None:
        payload = f"{game.seed}|{game.engine_version}|{role.player_id}|{role.version}|events-v1"
        seed = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")
    rng = random.Random(int(seed))
    goals=[]; assists=[]; points=[]
    for total in team_goals:
        g=a=0
        for _ in range(total):
            scored = rng.random() < role.goal_share
            primary = (not scored) and rng.random() < role.primary_assist_share
            secondary = (not scored) and rng.random() < role.secondary_assist_share
            g += int(scored)
            a += int(primary or secondary)
        goals.append(g); assists.append(a); points.append(g+a)
    return NHLPlayerEventPaths(role.player_id, tuple(goals), tuple(assists), tuple(points), int(seed), role.version)


def _over(values: tuple[int, ...], line: float) -> tuple[float,float,float]:
    if not math.isfinite(line): raise ValueError("line must be finite")
    if not values: raise ValueError("event paths required")
    diff=[x-line for x in values]; n=len(diff)
    w=sum(x>0 for x in diff); p=sum(x==0 for x in diff)
    return w/n,p/n,(n-w-p)/n


def goals_over(paths: NHLPlayerEventPaths, line: float) -> tuple[float,float,float]:
    return _over(paths.goals, line)


def points_over(paths: NHLPlayerEventPaths, line: float) -> tuple[float,float,float]:
    return _over(paths.points, line)
