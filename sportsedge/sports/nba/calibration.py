"""Deterministic temporal calibration for NBA binary market probabilities.

Calibration observations must represent predictions made before tipoff and outcomes
observed afterward. The calibrator never consumes sportsbook prices. Isotonic-like
binning is deliberately simple and auditable; unsupported/sparse bins shrink to the
identity probability rather than inventing certainty.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib, json, math
from typing import Iterable


@dataclass(frozen=True)
class NBAProbabilityObservation:
    game_id: str
    market_key: str
    predicted_at: datetime
    tipoff: datetime
    settled_at: datetime
    probability: float
    won: bool
    model_version: str

    def validate(self) -> None:
        if not all((self.game_id,self.market_key,self.model_version)):
            raise ValueError("calibration identity/version are required")
        for name,v in (("predicted_at",self.predicted_at),("tipoff",self.tipoff),("settled_at",self.settled_at)):
            if v.tzinfo is None or v.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")
        if not self.predicted_at < self.tipoff < self.settled_at:
            raise ValueError("calibration observation violates temporal order")
        if not math.isfinite(self.probability) or not 0 < self.probability < 1:
            raise ValueError("probability must be strictly between zero and one")


def calibration_digest(rows: Iterable[NBAProbabilityObservation]) -> str:
    data=tuple(sorted(rows,key=lambda r:(r.tipoff,r.game_id,r.market_key)))
    if not data: raise ValueError("calibration observations are required")
    for r in data: r.validate()
    payload=[{"game_id":r.game_id,"market":r.market_key,"predicted_at":r.predicted_at.isoformat(),"tipoff":r.tipoff.isoformat(),"settled_at":r.settled_at.isoformat(),"p":r.probability,"won":r.won,"model":r.model_version} for r in data]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()


@dataclass(frozen=True)
class NBACalibrator:
    bins: tuple[tuple[float,float,float,int], ...]  # low, high, empirical p, n
    training_sha256: str
    version: str="NBA_TEMPORAL_CALIBRATION_V1"

    def calibrate(self,p: float) -> float:
        if not math.isfinite(p) or not 0 < p < 1: raise ValueError("probability must be in (0,1)")
        for low,high,empirical,n in self.bins:
            if low <= p <= high:
                # Shrink small samples toward identity; reaches 50% empirical weight at n=25.
                w=n/(n+25.0)
                return min(0.999,max(0.001,w*empirical+(1-w)*p))
        return p


def fit_temporal_calibrator(rows: Iterable[NBAProbabilityObservation], *, as_of: datetime, bin_width: float=.10) -> NBACalibrator:
    if as_of.tzinfo is None or as_of.utcoffset() is None: raise ValueError("as_of must be timezone-aware")
    if not 0 < bin_width <= .5: raise ValueError("bin_width must be in (0,.5]")
    eligible=[]
    for r in rows:
        r.validate()
        if r.settled_at < as_of: eligible.append(r)
    if not eligible: raise ValueError("no PIT-eligible calibration history")
    buckets={}
    for r in eligible:
        i=min(int(r.probability/bin_width),int((1-1e-12)/bin_width))
        buckets.setdefault(i,[]).append(r)
    bins=[]
    for i,rs in sorted(buckets.items()):
        low=i*bin_width; high=min(1.0,(i+1)*bin_width)
        empirical=sum(r.won for r in rs)/len(rs)
        bins.append((low,high,empirical,len(rs)))
    return NBACalibrator(tuple(bins),calibration_digest(eligible))
