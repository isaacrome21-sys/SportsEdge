"""PIT-safe NBA quarter-share history and fitting.

Period parameters are learned only from completed-game quarter scores observed
before the requested as-of time. Sportsbook period lines are never model inputs.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib, json, math
from typing import Iterable

from .periods import NBAPeriodParameters


@dataclass(frozen=True)
class NBAPeriodObservation:
    game_id: str
    tipoff: datetime
    observed_at: datetime
    home_quarters: tuple[int,int,int,int]
    away_quarters: tuple[int,int,int,int]
    source: str
    source_version: str

    def validate(self) -> None:
        if not all((self.game_id,self.source,self.source_version)):
            raise ValueError("period observation identity/source are required")
        for name,value in (("tipoff",self.tipoff),("observed_at",self.observed_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.observed_at <= self.tipoff:
            raise ValueError("period result must be observed after tipoff")
        for q in (self.home_quarters,self.away_quarters):
            if len(q) != 4 or any(not isinstance(x,int) or x < 0 for x in q):
                raise ValueError("four non-negative integer regulation quarter scores are required")
        if sum(self.home_quarters)+sum(self.away_quarters) <= 0:
            raise ValueError("period observation must contain scoring")


def period_history_digest(rows: Iterable[NBAPeriodObservation]) -> str:
    data=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id)))
    if not data: raise ValueError("period observations are required")
    for r in data: r.validate()
    payload=[{"game_id":r.game_id,"tipoff":r.tipoff.isoformat(),"observed_at":r.observed_at.isoformat(),"home":r.home_quarters,"away":r.away_quarters,"source":r.source,"source_version":r.source_version} for r in data]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def fit_period_parameters(rows: Iterable[NBAPeriodObservation], *, as_of: datetime) -> NBAPeriodParameters:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    eligible=[]
    for r in rows:
        r.validate()
        if r.observed_at < as_of: eligible.append(r)
    if not eligible: raise ValueError("no PIT-eligible period history")
    quarter_points=[0,0,0,0]
    total=0
    for r in eligible:
        for i in range(4):
            x=r.home_quarters[i]+r.away_quarters[i]
            quarter_points[i]+=x; total+=x
    if total <= 0: raise ValueError("eligible period history has no scoring")
    shares=tuple(x/total for x in quarter_points)
    if any(not math.isfinite(x) or x <= 0 for x in shares):
        raise ValueError("each quarter needs observed scoring support")
    digest=period_history_digest(eligible)
    return NBAPeriodParameters(f"NBA_PERIOD_FIT_V1:{digest[:12]}",shares)
