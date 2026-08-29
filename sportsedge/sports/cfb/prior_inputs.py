"""Provider-neutral CFB preseason/early-season prior feature contract.

This module deliberately does not guess vendor endpoints. Automatic providers may fill
this contract only after PIT provenance is demonstrated; Manual/Hybrid may supply
verified artifacts with the same semantics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any


class CFBPriorInputError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBPriorInputError(f"{field}:TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBPriorInputError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBPriorInputError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBPriorInputError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBPriorInputError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class CFBPriorInputs:
    team_id: str
    season: int
    prior_season_rating: float
    returning_production: float
    talent_composite: float
    portal_impact: float
    qb_continuity: float
    ol_continuity: float
    skill_continuity: float
    defensive_continuity: float
    coaching_continuity: float
    special_teams_prior: float
    source_asof_ts: str
    feature_asof_ts: str
    game_start_ts: str
    source_id: str
    source_version: str
    provenance_id: str

    def validate(self) -> "CFBPriorInputs":
        if not self.team_id or not self.source_id or not self.source_version or not self.provenance_id:
            raise CFBPriorInputError("PRIOR_IDENTITY_OR_PROVENANCE_REQUIRED")
        source = _utc(self.source_asof_ts, "source_asof_ts")
        feature = _utc(self.feature_asof_ts, "feature_asof_ts")
        game = _utc(self.game_start_ts, "game_start_ts")
        if source > feature or feature >= game:
            raise CFBPriorInputError("PRIOR_PIT_VIOLATION")
        _finite(self.prior_season_rating, "prior_season_rating")
        _finite(self.talent_composite, "talent_composite")
        _finite(self.portal_impact, "portal_impact")
        _finite(self.special_teams_prior, "special_teams_prior")
        for field in (
            "returning_production", "qb_continuity", "ol_continuity", "skill_continuity",
            "defensive_continuity", "coaching_continuity",
        ):
            value = _finite(getattr(self, field), field)
            if not 0.0 <= value <= 1.0:
                raise CFBPriorInputError(f"{field}:RANGE_0_1_REQUIRED")
        return self

    def to_features(self) -> dict[str, float]:
        self.validate()
        return {
            "prior_season_rating": float(self.prior_season_rating),
            "returning_production": float(self.returning_production),
            "talent_composite": float(self.talent_composite),
            "portal_impact": float(self.portal_impact),
            "qb_continuity": float(self.qb_continuity),
            "ol_continuity": float(self.ol_continuity),
            "skill_continuity": float(self.skill_continuity),
            "defensive_continuity": float(self.defensive_continuity),
            "coaching_continuity": float(self.coaching_continuity),
            "special_teams_prior": float(self.special_teams_prior),
        }

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)
