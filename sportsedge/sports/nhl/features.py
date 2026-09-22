"""PIT-safe NHL model input contracts.

All snapshots must describe information available strictly before puck drop.  This
module stores inputs/provenance only; it does not claim fitted predictive quality.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import math


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class GoalieState:
    goalie_id: str
    status: str  # CONFIRMED or PROJECTED
    save_pct: float
    goals_saved_above_expected_per_60: float
    sample_shots: int

    def validate(self) -> None:
        if not self.goalie_id:
            raise ValueError("goalie_id is required")
        if self.status not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("goalie status must be CONFIRMED or PROJECTED")
        if not 0.0 <= self.save_pct <= 1.0:
            raise ValueError("save_pct must be in [0, 1]")
        if not math.isfinite(self.goals_saved_above_expected_per_60):
            raise ValueError("GSAx/60 must be finite")
        if self.sample_shots < 0:
            raise ValueError("sample_shots must be non-negative")


@dataclass(frozen=True)
class TeamSnapshot:
    team_id: str
    xgf_per_60: float
    xga_per_60: float
    shots_for_per_60: float
    shots_against_per_60: float
    power_play_xg_per_60: float
    penalty_kill_xga_per_60: float
    rest_days: float
    travel_km: float
    lineup_strength: float

    def validate(self) -> None:
        if not self.team_id:
            raise ValueError("team_id is required")
        nonnegative = (
            self.xgf_per_60, self.xga_per_60, self.shots_for_per_60,
            self.shots_against_per_60, self.power_play_xg_per_60,
            self.penalty_kill_xga_per_60, self.rest_days, self.travel_km,
        )
        if any((not math.isfinite(v) or v < 0) for v in nonnegative):
            raise ValueError("rate/rest/travel inputs must be finite and non-negative")
        if not math.isfinite(self.lineup_strength):
            raise ValueError("lineup_strength must be finite")


@dataclass(frozen=True)
class NHLFeatureSnapshot:
    game_id: str
    puck_drop: datetime
    captured_at: datetime
    home: TeamSnapshot
    away: TeamSnapshot
    home_goalie: GoalieState
    away_goalie: GoalieState
    source: str
    source_version: str

    def validate(self) -> None:
        if not self.game_id or not self.source or not self.source_version:
            raise ValueError("game_id/source/source_version are required")
        _aware(self.puck_drop, "puck_drop")
        _aware(self.captured_at, "captured_at")
        if self.captured_at >= self.puck_drop:
            raise ValueError("PIT violation: snapshot must be captured before puck drop")
        self.home.validate(); self.away.validate()
        self.home_goalie.validate(); self.away_goalie.validate()
        if self.home.team_id == self.away.team_id:
            raise ValueError("home and away teams must differ")

    @property
    def goalie_certainty(self) -> str:
        return "CONFIRMED" if self.home_goalie.status == self.away_goalie.status == "CONFIRMED" else "PROJECTED"
