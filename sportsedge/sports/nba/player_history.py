"""PIT-safe NBA player box-score history and deterministic role fitting.

Completed-game observations may be used only when observed before the requested
as-of cutoff. The fitter never consumes sportsbook props or post-cutoff games.
Uncertain injury statuses require an explicit caller-supplied minutes override;
we do not invent an availability probability.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from statistics import fmean, pstdev
from typing import Iterable

from .player_stats import NBAPlayerStatRole


@dataclass(frozen=True)
class NBAPlayerBoxObservation:
    game_id: str
    player_id: str
    team_id: str
    tipoff: datetime
    observed_at: datetime
    minutes: float
    points: int
    rebounds: int
    assists: int
    threes: int
    team_points: int
    source: str
    source_version: str

    def validate(self) -> None:
        if not all((self.game_id,self.player_id,self.team_id,self.source,self.source_version)):
            raise ValueError("player observation identity/source are required")
        for name,value in (("tipoff",self.tipoff),("observed_at",self.observed_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.observed_at <= self.tipoff:
            raise ValueError("box observation must be post-tipoff")
        if not math.isfinite(self.minutes) or not 0 <= self.minutes <= 48:
            raise ValueError("minutes must be finite in [0,48]")
        if min(self.points,self.rebounds,self.assists,self.threes,self.team_points) < 0:
            raise ValueError("box counts must be non-negative")
        if self.points > self.team_points:
            raise ValueError("player points cannot exceed team points")


def player_history_digest(rows: Iterable[NBAPlayerBoxObservation]) -> str:
    ordered=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id,r.player_id)))
    if not ordered: raise ValueError("player observations are required")
    for r in ordered: r.validate()
    payload=[r.__dict__ | {"tipoff":r.tipoff.isoformat(),"observed_at":r.observed_at.isoformat()} for r in ordered]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def fit_player_role(rows: Iterable[NBAPlayerBoxObservation], *, player_id: str, team: str,
                    as_of: datetime, status: str="AVAILABLE",
                    uncertain_minutes_override: tuple[float,float] | None=None) -> NBAPlayerStatRole:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if team not in {"HOME","AWAY"}: raise ValueError("team must be HOME or AWAY")
    eligible=[]
    for r in rows:
        r.validate()
        if r.player_id == player_id and r.observed_at < as_of:
            eligible.append(r)
    if not eligible: raise ValueError("no PIT-eligible player history")
    eligible.sort(key=lambda r:(r.tipoff,r.game_id))
    if status == "OUT":
        mm=ms=0.0
    elif status in {"QUESTIONABLE","DOUBTFUL"}:
        if uncertain_minutes_override is None:
            raise ValueError("uncertain status requires explicit minutes override")
        mm,ms=uncertain_minutes_override
    elif status in {"AVAILABLE","PROBABLE"}:
        mins=[r.minutes for r in eligible]; mm=fmean(mins); ms=pstdev(mins)
    else:
        raise ValueError("unsupported availability status")
    active=[r for r in eligible if r.minutes > 0]
    if not active: raise ValueError("no active-minute player history")
    point_share=fmean((r.points/r.team_points) if r.team_points else 0.0 for r in active)
    reb=fmean(r.rebounds/r.minutes for r in active)
    ast=fmean(r.assists/r.minutes for r in active)
    three=fmean(r.threes/r.minutes for r in active)
    digest=player_history_digest(eligible)
    role=NBAPlayerStatRole(player_id,team,f"NBA_PLAYER_ROLE_V1:{digest[:12]}",mm,ms,point_share,reb,ast,three)
    role.validate()
    return role
