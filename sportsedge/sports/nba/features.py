"""PIT-safe NBA feature, injury, and rotation input contracts.

These objects capture only information available before tipoff. They are model
inputs/provenance, not fitted predictions or claims of predictive performance.
"""
from dataclasses import dataclass
from datetime import datetime
import math


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class NBAPlayerRole:
    player_id: str
    team_id: str
    status: str
    starter: bool
    minutes_mean: float
    minutes_sd: float
    usage_rate: float

    def validate(self) -> None:
        if not self.player_id or not self.team_id:
            raise ValueError("player_id/team_id are required")
        if self.status not in {"AVAILABLE", "PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT"}:
            raise ValueError("unsupported availability status")
        vals = (self.minutes_mean, self.minutes_sd, self.usage_rate)
        if any(not math.isfinite(v) for v in vals):
            raise ValueError("role inputs must be finite")
        if not 0.0 <= self.minutes_mean <= 48.0 or self.minutes_sd < 0.0:
            raise ValueError("invalid minutes distribution")
        if not 0.0 <= self.usage_rate <= 1.0:
            raise ValueError("usage_rate must be in [0, 1]")
        if self.status == "OUT" and (self.minutes_mean != 0.0 or self.minutes_sd != 0.0):
            raise ValueError("OUT players must have zero minutes distribution")


@dataclass(frozen=True)
class NBATeamState:
    team_id: str
    pace: float
    offensive_rating: float
    defensive_rating: float
    rest_days: float
    travel_km: float
    roles: tuple[NBAPlayerRole, ...]

    def validate(self) -> None:
        if not self.team_id:
            raise ValueError("team_id is required")
        rates = (self.pace, self.offensive_rating, self.defensive_rating)
        if any(not math.isfinite(v) or v <= 0 for v in rates):
            raise ValueError("pace/ratings must be finite and positive")
        if not math.isfinite(self.rest_days) or self.rest_days < 0:
            raise ValueError("rest_days must be finite and non-negative")
        if not math.isfinite(self.travel_km) or self.travel_km < 0:
            raise ValueError("travel_km must be finite and non-negative")
        if not self.roles:
            raise ValueError("rotation roles are required")
        ids = [r.player_id for r in self.roles]
        if len(ids) != len(set(ids)):
            raise ValueError("player roles must be unique within a team")
        for role in self.roles:
            role.validate()
            if role.team_id != self.team_id:
                raise ValueError("player role team mismatch")


@dataclass(frozen=True)
class NBAFeatureSnapshot:
    game_id: str
    tipoff: datetime
    captured_at: datetime
    home: NBATeamState
    away: NBATeamState
    source: str
    source_version: str

    def validate(self) -> None:
        if not self.game_id or not self.source or not self.source_version:
            raise ValueError("game_id/source/source_version are required")
        _aware(self.tipoff, "tipoff")
        _aware(self.captured_at, "captured_at")
        if self.captured_at >= self.tipoff:
            raise ValueError("PIT violation: snapshot must be captured before tipoff")
        self.home.validate(); self.away.validate()
        if self.home.team_id == self.away.team_id:
            raise ValueError("home and away teams must differ")

    @property
    def uncertain_players(self) -> tuple[str, ...]:
        uncertain = {"QUESTIONABLE", "DOUBTFUL"}
        return tuple(r.player_id for t in (self.home, self.away) for r in t.roles if r.status in uncertain)
