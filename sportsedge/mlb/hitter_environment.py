"""Hitter-specific MLB environment decomposition.

Inspired by publicly described BallparkPal concepts: separate stadium and weather
components, outcome-specific effects, and hitter spray-profile sensitivity.
This module does not encode BallparkPal proprietary coefficients. All park/weather
factors are supplied as point-in-time inputs and remain external evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite


@dataclass(frozen=True)
class OutcomeFactors:
    hr: float
    xbh: float
    single: float

    def __post_init__(self) -> None:
        for name, value in (("hr", self.hr), ("xbh", self.xbh), ("single", self.single)):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} factor must be finite and > 0")


@dataclass(frozen=True)
class SprayProfile:
    pull: float
    center: float
    opposite: float

    def normalized(self) -> "SprayProfile":
        vals = (self.pull, self.center, self.opposite)
        if any((not isfinite(v) or v < 0) for v in vals):
            raise ValueError("spray weights must be finite and >= 0")
        total = sum(vals)
        if total <= 0:
            raise ValueError("spray weights must sum to > 0")
        return SprayProfile(*(v / total for v in vals))


@dataclass(frozen=True)
class DirectionalFactors:
    pull: OutcomeFactors
    center: OutcomeFactors
    opposite: OutcomeFactors


@dataclass(frozen=True)
class TimedEnvironmentSnapshot:
    stadium: DirectionalFactors
    weather: DirectionalFactors
    as_of_utc: str
    source: str

    def _timestamp(self) -> datetime:
        ts = datetime.fromisoformat(self.as_of_utc.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    def age_seconds(self, now_utc: datetime) -> float:
        now = now_utc.astimezone(timezone.utc)
        return max(0.0, (now - self._timestamp()).total_seconds())

    def is_fresh(self, now_utc: datetime, *, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        return self.age_seconds(now_utc) <= ttl_seconds


@dataclass(frozen=True)
class HitterEnvironmentEffect:
    stadium: OutcomeFactors
    weather: OutcomeFactors
    combined: OutcomeFactors
    as_of_utc: str
    source: str
    promotion_evidence: bool = False


def _weighted(profile: SprayProfile, factors: DirectionalFactors) -> OutcomeFactors:
    p = profile.normalized()
    return OutcomeFactors(
        hr=p.pull * factors.pull.hr + p.center * factors.center.hr + p.opposite * factors.opposite.hr,
        xbh=p.pull * factors.pull.xbh + p.center * factors.center.xbh + p.opposite * factors.opposite.xbh,
        single=p.pull * factors.pull.single + p.center * factors.center.single + p.opposite * factors.opposite.single,
    )


def hitter_environment_effect(
    profile: SprayProfile,
    snapshot: TimedEnvironmentSnapshot,
    *,
    now_utc: datetime,
    ttl_seconds: int = 3600,
) -> HitterEnvironmentEffect:
    """Return hitter-specific stadium/weather/combined multipliers.

    Fails closed on stale snapshots rather than silently substituting neutral values.
    """
    if not snapshot.is_fresh(now_utc, ttl_seconds=ttl_seconds):
        raise ValueError("ENVIRONMENT_SNAPSHOT_STALE")
    stadium = _weighted(profile, snapshot.stadium)
    weather = _weighted(profile, snapshot.weather)
    combined = OutcomeFactors(
        hr=stadium.hr * weather.hr,
        xbh=stadium.xbh * weather.xbh,
        single=stadium.single * weather.single,
    )
    return HitterEnvironmentEffect(
        stadium=stadium,
        weather=weather,
        combined=combined,
        as_of_utc=snapshot.as_of_utc,
        source=snapshot.source,
    )


def aggregate_lineup_environment(effects: tuple[HitterEnvironmentEffect, ...], pa_weights: tuple[float, ...]) -> OutcomeFactors:
    """Aggregate hitter-specific effects for game-level use using expected PA weights."""
    if not effects or len(effects) != len(pa_weights):
        raise ValueError("effects and pa_weights must be non-empty and aligned")
    if any((not isfinite(w) or w < 0) for w in pa_weights):
        raise ValueError("pa_weights must be finite and >= 0")
    total = sum(pa_weights)
    if total <= 0:
        raise ValueError("pa_weights must sum to > 0")
    weights = tuple(w / total for w in pa_weights)
    return OutcomeFactors(
        hr=sum(w * e.combined.hr for w, e in zip(weights, effects)),
        xbh=sum(w * e.combined.xbh for w, e in zip(weights, effects)),
        single=sum(w * e.combined.single for w, e in zip(weights, effects)),
    )
