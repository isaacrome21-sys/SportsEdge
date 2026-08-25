"""Structural Engine C special-teams resolver.

Engine C consumes raw Engine A play paths. It resolves field-goal attempts and
post-touchdown try decisions without creating an independent game simulation.
All scoring remains traceable to the original play path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .drive_play import FootballPlayPath, PlayEvent
from .football_path import FootballGamePath, ScoringEvent


@dataclass(frozen=True)
class SpecialTeamsProfile:
    """Market-blind structural candidate inputs for one team's kick/try layer."""

    team: str
    kicker_id: str
    kicker_active: bool | None
    fg_base_skill: float = 0.86
    xp_make_rate: float = 0.94
    two_point_attempt_rate: float = 0.0
    two_point_success_rate: float = 0.48
    wind_mph: float = 0.0
    roof_closed: bool = False

    def __post_init__(self) -> None:
        if not str(self.team).strip():
            raise ValueError("SPECIAL_TEAMS_TEAM_REQUIRED")
        if not str(self.kicker_id).strip():
            raise ValueError("KICKER_ID_REQUIRED")
        if self.kicker_active is not None and not isinstance(self.kicker_active, bool):
            raise ValueError("KICKER_ACTIVE_STATE_INVALID")
        for name in (
            "fg_base_skill",
            "xp_make_rate",
            "two_point_attempt_rate",
            "two_point_success_rate",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"SPECIAL_TEAMS_RATE_OUT_OF_RANGE:{name}")
        if float(self.wind_mph) < 0:
            raise ValueError("WIND_MPH_MUST_BE_NONNEGATIVE")
        if not isinstance(self.roof_closed, bool):
            raise ValueError("ROOF_CLOSED_MUST_BE_BOOLEAN")


@dataclass(frozen=True)
class SpecialTeamsEvent:
    source_play_id: int
    period: int
    clock_seconds_remaining: int
    team: str
    event_type: str
    points: int
    kicker_id: str | None = None
    kick_distance: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_play_id, bool) or not isinstance(self.source_play_id, int) or self.source_play_id <= 0:
            raise ValueError("SPECIAL_TEAMS_SOURCE_PLAY_ID_INVALID")
        if self.period not in (1, 2, 3, 4):
            raise ValueError("SPECIAL_TEAMS_PERIOD_INVALID")
        if not 0 <= self.clock_seconds_remaining <= 900:
            raise ValueError("SPECIAL_TEAMS_CLOCK_INVALID")
        if not str(self.team).strip():
            raise ValueError("SPECIAL_TEAMS_EVENT_TEAM_REQUIRED")
        allowed = {
            "FG_MADE": 3,
            "FG_MISSED": 0,
            "XP_MADE": 1,
            "XP_MISSED": 0,
            "TWO_POINT_MADE": 2,
            "TWO_POINT_MISSED": 0,
        }
        if self.event_type not in allowed:
            raise ValueError(f"SPECIAL_TEAMS_EVENT_TYPE_INVALID:{self.event_type}")
        if self.points != allowed[self.event_type]:
            raise ValueError("SPECIAL_TEAMS_EVENT_POINTS_INVALID")
        if self.event_type.startswith("FG_"):
            if self.kicker_id is None or self.kick_distance is None:
                raise ValueError("FIELD_GOAL_EVENT_METADATA_REQUIRED")
        if self.event_type.startswith("XP_") and self.kicker_id is None:
            raise ValueError("XP_EVENT_KICKER_REQUIRED")


@dataclass(frozen=True)
class ResolvedFootballPath:
    """Engine A path plus Engine C kick/try outcomes."""

    base_path: FootballPlayPath
    special_teams_events: tuple[SpecialTeamsEvent, ...]

    def to_scoring_path(self) -> FootballGamePath:
        base = list(self.base_path.to_scoring_path().events)
        for index, event in enumerate(self.special_teams_events):
            if event.points <= 0:
                continue
            base.append(
                ScoringEvent(
                    event_id=(
                        f"{self.base_path.simulation_id}:play:{event.source_play_id:05d}:"
                        f"st:{index:03d}"
                    ),
                    period=event.period,
                    clock_seconds_remaining=event.clock_seconds_remaining,
                    team=event.team,
                    points=event.points,
                    score_type=event.event_type,
                )
            )
        ordered = tuple(
            sorted(
                base,
                key=lambda event: (
                    event.period,
                    -event.clock_seconds_remaining,
                    event.event_id,
                ),
            )
        )
        path = FootballGamePath(
            game_id=self.base_path.game_id,
            simulation_id=self.base_path.simulation_id,
            home_team=self.base_path.home_team,
            away_team=self.base_path.away_team,
            events=ordered,
        )
        path.assert_conservation()
        return path

    def assert_reconciliation(self) -> None:
        raw = self.base_path.to_scoring_path().to_market_row()
        resolved = self.to_scoring_path().to_market_row()
        home_st = sum(
            event.points
            for event in self.special_teams_events
            if event.team == self.base_path.home_team
        )
        away_st = sum(
            event.points
            for event in self.special_teams_events
            if event.team == self.base_path.away_team
        )
        if resolved["home_score"] != raw["home_score"] + home_st:
            raise ValueError("ENGINE_C_HOME_SCORE_RECONCILIATION_FAILED")
        if resolved["away_score"] != raw["away_score"] + away_st:
            raise ValueError("ENGINE_C_AWAY_SCORE_RECONCILIATION_FAILED")

        fg_attempt_ids = [
            play.play_id
            for play in self.base_path.plays
            if play.play_type.upper() == "FIELD_GOAL"
        ]
        fg_event_ids = [
            event.source_play_id
            for event in self.special_teams_events
            if event.event_type.startswith("FG_")
        ]
        if len(fg_event_ids) != len(fg_attempt_ids):
            raise ValueError("ENGINE_C_FIELD_GOAL_RESOLUTION_COUNT_INVALID")
        if sorted(fg_event_ids) != sorted(fg_attempt_ids):
            raise ValueError("ENGINE_C_FIELD_GOAL_ATTEMPT_RECONCILIATION_FAILED")

        td_play_ids = [
            play.play_id
            for play in self.base_path.plays
            if play.score_type == "TOUCHDOWN_CANDIDATE" and play.points == 6
        ]
        try_event_ids = [
            event.source_play_id
            for event in self.special_teams_events
            if event.event_type.startswith("XP_") or event.event_type.startswith("TWO_POINT_")
        ]
        if len(try_event_ids) != len(td_play_ids):
            raise ValueError("ENGINE_C_TD_TRY_RESOLUTION_COUNT_INVALID")
        if sorted(try_event_ids) != sorted(td_play_ids):
            raise ValueError("ENGINE_C_TD_TRY_RECONCILIATION_FAILED")


class EngineCSpecialTeamsResolver:
    """Seeded Engine C resolver for FG and post-TD try outcomes."""

    def __init__(
        self,
        *,
        home_profile: SpecialTeamsProfile,
        away_profile: SpecialTeamsProfile,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not isinstance(home_profile, SpecialTeamsProfile) or not isinstance(away_profile, SpecialTeamsProfile):
            raise TypeError("SPECIAL_TEAMS_PROFILE_REQUIRED")
        if home_profile.team == away_profile.team:
            raise ValueError("SPECIAL_TEAMS_HOME_AWAY_COLLISION")
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    def _profile(self, path: FootballPlayPath, team: str) -> SpecialTeamsProfile:
        if team == path.home_team:
            profile = self.home_profile
        elif team == path.away_team:
            profile = self.away_profile
        else:
            raise ValueError("SPECIAL_TEAMS_TEAM_NOT_IN_PATH")
        if profile.team != team:
            raise ValueError("SPECIAL_TEAMS_PROFILE_TEAM_MISMATCH")
        return profile

    @staticmethod
    def _wind_penalty(profile: SpecialTeamsProfile) -> float:
        if profile.roof_closed:
            return 0.0
        return max(0.0, float(profile.wind_mph) - 8.0) * 0.006

    def _fg_probability(self, profile: SpecialTeamsProfile, distance: int) -> float:
        distance_penalty = max(0, int(distance) - 40) * 0.012
        probability = float(profile.fg_base_skill) - distance_penalty - self._wind_penalty(profile)
        return max(0.0, min(1.0, probability))

    def _xp_probability(self, profile: SpecialTeamsProfile) -> float:
        probability = float(profile.xp_make_rate) - 0.35 * self._wind_penalty(profile)
        return max(0.0, min(1.0, probability))

    @staticmethod
    def _require_kicker(profile: SpecialTeamsProfile) -> None:
        if profile.kicker_active is None:
            raise ValueError(f"KICKER_STATUS_UNRESOLVED:{profile.kicker_id}")
        if profile.kicker_active is not True:
            raise ValueError(f"KICKER_INACTIVE:{profile.kicker_id}")

    def _resolve_td_try(self, path: FootballPlayPath, play: PlayEvent) -> SpecialTeamsEvent:
        profile = self._profile(path, play.possession)
        if self.rng.random() < profile.two_point_attempt_rate:
            made = bool(self.rng.random() < profile.two_point_success_rate)
            return SpecialTeamsEvent(
                source_play_id=play.play_id,
                period=play.quarter,
                clock_seconds_remaining=play.clock_seconds_remaining,
                team=play.possession,
                event_type="TWO_POINT_MADE" if made else "TWO_POINT_MISSED",
                points=2 if made else 0,
            )

        self._require_kicker(profile)
        made = bool(self.rng.random() < self._xp_probability(profile))
        return SpecialTeamsEvent(
            source_play_id=play.play_id,
            period=play.quarter,
            clock_seconds_remaining=play.clock_seconds_remaining,
            team=play.possession,
            event_type="XP_MADE" if made else "XP_MISSED",
            points=1 if made else 0,
            kicker_id=profile.kicker_id,
        )

    def _resolve_field_goal(self, path: FootballPlayPath, play: PlayEvent) -> SpecialTeamsEvent:
        profile = self._profile(path, play.possession)
        self._require_kicker(profile)
        if play.kick_distance is None:
            raise ValueError("FIELD_GOAL_DISTANCE_REQUIRED")
        made = bool(self.rng.random() < self._fg_probability(profile, play.kick_distance))
        return SpecialTeamsEvent(
            source_play_id=play.play_id,
            period=play.quarter,
            clock_seconds_remaining=play.clock_seconds_remaining,
            team=play.possession,
            event_type="FG_MADE" if made else "FG_MISSED",
            points=3 if made else 0,
            kicker_id=profile.kicker_id,
            kick_distance=play.kick_distance,
        )

    def resolve(self, path: FootballPlayPath) -> ResolvedFootballPath:
        if not isinstance(path, FootballPlayPath):
            raise TypeError("FOOTBALL_PLAY_PATH_REQUIRED")
        if self.home_profile.team != path.home_team or self.away_profile.team != path.away_team:
            raise ValueError("SPECIAL_TEAMS_PATH_TEAM_MISMATCH")

        events: list[SpecialTeamsEvent] = []
        for play in path.plays:
            if play.score_type == "TOUCHDOWN_CANDIDATE" and play.points == 6:
                events.append(self._resolve_td_try(path, play))
            elif play.play_type.upper() == "FIELD_GOAL":
                events.append(self._resolve_field_goal(path, play))

        resolved = ResolvedFootballPath(path, tuple(events))
        resolved.assert_reconciliation()
        return resolved

    def resolve_many(self, paths: list[FootballPlayPath]) -> list[ResolvedFootballPath]:
        return [self.resolve(path) for path in paths]
