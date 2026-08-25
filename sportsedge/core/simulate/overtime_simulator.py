"""Predictive 2026 NFL regular-season overtime over shared A+C primitives.

Overtime begins with a real Engine C kickoff rather than a fixed field-position
shortcut. Kickoffs, onside recoveries, punt returns, missed field goals and
turnovers determine the next possession and starting yardline through the same
field-position resolver used in regulation. Return touchdowns are scored on the
same opportunity path and use the Rule 16-aware try contract.

All numerical drive/field-position/return inputs remain structural candidates
until fitted from point-in-time history. No sportsbook line or price is accepted
by this simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from .field_position import (
    NFLFieldPositionProfile,
    NFLFieldPositionResolver,
    NFLPossessionTransition,
)
from .football_path import FootballGamePath
from .overtime import (
    NFLRegularSeasonOTOpportunity,
    NFLRegularSeasonOvertimeResult,
    settle_nfl_regular_season_overtime,
)
from .return_scoring import NFLReturnScoringProfile, NFLReturnScoringResolver
from .special_teams import (
    EngineCSpecialTeamsResolver,
    ResolvedFootballPath,
    SpecialTeamsProfile,
)


_CONTINUATION_ERRORS = {
    "OVERTIME_SECOND_OPPORTUNITY_REQUIRED",
    "OVERTIME_SUDDEN_DEATH_CONTINUATION_REQUIRED",
}


@dataclass(frozen=True)
class NFLRegularSeasonOTPlay:
    opportunity_index: int
    play_index: int
    opportunity_team: str
    clock_end_seconds_remaining: int
    down: int
    distance: int
    yardline_100: int
    play_type: str
    yards: int
    pass_complete: bool | None = None
    turnover_type: str | None = None
    kick_distance: int | None = None
    raw_points: int = 0
    special_teams_points: int = 0
    special_teams_event_type: str | None = None
    defensive_points: int = 0
    defensive_scoring_team: str | None = None
    return_points: int = 0
    return_scoring_team: str | None = None
    transition_index: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.opportunity_index, bool) or not isinstance(self.opportunity_index, int) or self.opportunity_index <= 0:
            raise ValueError("OT_PLAY_OPPORTUNITY_INDEX_INVALID")
        if isinstance(self.play_index, bool) or not isinstance(self.play_index, int) or self.play_index <= 0:
            raise ValueError("OT_PLAY_INDEX_INVALID")
        if not str(self.opportunity_team).strip():
            raise ValueError("OT_PLAY_TEAM_REQUIRED")
        if not 0 <= self.clock_end_seconds_remaining <= 600:
            raise ValueError("OT_PLAY_CLOCK_INVALID")
        if self.down not in (1, 2, 3, 4):
            raise ValueError("OT_PLAY_DOWN_INVALID")
        if isinstance(self.distance, bool) or not isinstance(self.distance, int) or self.distance <= 0:
            raise ValueError("OT_PLAY_DISTANCE_INVALID")
        if isinstance(self.yardline_100, bool) or not isinstance(self.yardline_100, int) or not 0 <= self.yardline_100 <= 100:
            raise ValueError("OT_PLAY_YARDLINE_INVALID")
        if not str(self.play_type).strip():
            raise ValueError("OT_PLAY_TYPE_REQUIRED")
        if self.raw_points not in (0, 6):
            raise ValueError("OT_PLAY_RAW_POINTS_INVALID")
        if self.special_teams_points not in (0, 1, 2, 3):
            raise ValueError("OT_PLAY_SPECIAL_TEAMS_POINTS_INVALID")
        if self.defensive_points not in (0, 2, 6):
            raise ValueError("OT_PLAY_DEFENSIVE_POINTS_INVALID")
        if self.return_points not in (0, 6):
            raise ValueError("OT_PLAY_RETURN_POINTS_INVALID")
        scoring_buckets = sum(value > 0 for value in (self.raw_points, self.defensive_points, self.return_points))
        if scoring_buckets > 1:
            raise ValueError("OT_PLAY_SCORING_BUCKET_COLLISION")
        if self.raw_points == 6 and self.play_type not in {"PASS", "RUSH"}:
            raise ValueError("OT_TOUCHDOWN_PLAY_TYPE_INVALID")
        if self.play_type == "PASS" and not isinstance(self.pass_complete, bool):
            raise ValueError("OT_PASS_COMPLETION_STATE_REQUIRED")
        if self.play_type != "PASS" and self.pass_complete is not None:
            raise ValueError("OT_NON_PASS_COMPLETION_STATE_INVALID")
        if self.play_type == "SACK":
            if self.yards >= 0:
                raise ValueError("OT_SACK_YARDS_MUST_BE_NEGATIVE")
            if self.turnover_type is not None:
                raise ValueError("OT_SACK_TURNOVER_COLLISION")
        if self.play_type == "FIELD_GOAL":
            if self.kick_distance is None:
                raise ValueError("OT_FIELD_GOAL_DISTANCE_REQUIRED")
            if self.special_teams_event_type not in {"FG_MADE", "FG_MISSED"}:
                raise ValueError("OT_FIELD_GOAL_RESULT_REQUIRED")
        if self.special_teams_points > 0 and self.special_teams_event_type is None:
            raise ValueError("OT_SPECIAL_TEAMS_EVENT_TYPE_REQUIRED")
        if self.defensive_points > 0 and not str(self.defensive_scoring_team or "").strip():
            raise ValueError("OT_DEFENSIVE_SCORING_TEAM_REQUIRED")
        if self.defensive_points == 0 and self.defensive_scoring_team is not None:
            raise ValueError("OT_ZERO_DEFENSIVE_POINTS_HAS_SCORING_TEAM")
        if self.defensive_points == 6:
            if self.turnover_type not in {"INTERCEPTION", "FUMBLE"}:
                raise ValueError("OT_DEFENSIVE_RETURN_TD_REQUIRES_TURNOVER")
            if self.defensive_scoring_team == self.opportunity_team:
                raise ValueError("OT_DEFENSIVE_RETURN_TD_TEAM_INVALID")
        if self.return_points > 0:
            if self.play_type not in {"KICKOFF_RETURN", "PUNT_RETURN"}:
                raise ValueError("OT_RETURN_TD_PLAY_TYPE_INVALID")
            if self.return_scoring_team != self.opportunity_team:
                raise ValueError("OT_RETURN_TD_SCORING_TEAM_INVALID")
        elif self.return_scoring_team is not None:
            raise ValueError("OT_ZERO_RETURN_POINTS_HAS_SCORING_TEAM")
        if self.play_type in {"KICKOFF_RETURN", "PUNT_RETURN", "ONSIDE_KICK"}:
            if self.transition_index is None:
                raise ValueError("OT_RETURN_PLAY_TRANSITION_REQUIRED")
        if self.transition_index is not None and (
            isinstance(self.transition_index, bool)
            or not isinstance(self.transition_index, int)
            or self.transition_index <= 0
        ):
            raise ValueError("OT_PLAY_TRANSITION_INDEX_INVALID")


@dataclass(frozen=True)
class NFLRegularSeasonOTSimulation:
    regulation_path: ResolvedFootballPath
    plays: tuple[NFLRegularSeasonOTPlay, ...]
    opportunities: tuple[NFLRegularSeasonOTOpportunity, ...]
    settlement: NFLRegularSeasonOvertimeResult
    transitions: tuple[NFLPossessionTransition, ...] = ()

    def __post_init__(self) -> None:
        if self.settlement.regulation_path != self.regulation_path:
            raise ValueError("OT_SIMULATION_REGULATION_PATH_MISMATCH")
        if self.settlement.opportunities != self.opportunities:
            raise ValueError("OT_SIMULATION_SETTLEMENT_OPPORTUNITY_MISMATCH")
        indexes = [play.play_index for play in self.plays]
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("OT_PLAY_INDEX_SEQUENCE_INVALID")
        clocks = [play.clock_end_seconds_remaining for play in self.plays]
        if clocks != sorted(clocks, reverse=True):
            raise ValueError("OT_PLAY_CLOCK_ORDER_INVALID")
        transition_indexes = [item.transition_index for item in self.transitions]
        if transition_indexes != list(range(1, len(transition_indexes) + 1)):
            raise ValueError("OT_TRANSITION_INDEX_SEQUENCE_INVALID")
        if any(item.period != 5 for item in self.transitions):
            raise ValueError("OT_TRANSITION_PERIOD_INVALID")

    def assert_reconciliation(self) -> None:
        transition_ids = {item.transition_index for item in self.transitions}
        for play in self.plays:
            if play.transition_index is not None and play.transition_index not in transition_ids:
                raise ValueError("OT_PLAY_TRANSITION_NOT_FOUND")
            if play.return_points > 0:
                transition = next(item for item in self.transitions if item.transition_index == play.transition_index)
                if transition.creates_next_drive:
                    raise ValueError("OT_SCORING_RETURN_TRANSITION_CANNOT_CREATE_DRIVE")

        for opportunity in self.opportunities:
            points = sum(
                play.raw_points
                + play.special_teams_points
                + play.defensive_points
                + play.return_points
                for play in self.plays
                if play.opportunity_index == opportunity.opportunity_index
            )
            if points != opportunity.points:
                raise ValueError("OT_OPPORTUNITY_PLAY_SCORE_RECONCILIATION_FAILED")

        scoring = self.settlement.to_scoring_path().to_market_row()
        regulation = self.regulation_path.to_scoring_path().to_market_row()
        ot_home = scoring["home_score"] - regulation["home_score"]
        ot_away = scoring["away_score"] - regulation["away_score"]
        expected_home = sum(
            item.points
            for item in self.opportunities
            if item.scoring_team == self.regulation_path.base_path.home_team
        )
        expected_away = sum(
            item.points
            for item in self.opportunities
            if item.scoring_team == self.regulation_path.base_path.away_team
        )
        if ot_home != expected_home:
            raise ValueError("OT_HOME_SCORE_RECONCILIATION_FAILED")
        if ot_away != expected_away:
            raise ValueError("OT_AWAY_SCORE_RECONCILIATION_FAILED")

    def to_scoring_path(self) -> FootballGamePath:
        self.assert_reconciliation()
        return self.settlement.to_scoring_path()


@dataclass(frozen=True)
class _OTDriveResult:
    opportunity: NFLRegularSeasonOTOpportunity
    plays: tuple[NFLRegularSeasonOTPlay, ...]
    next_play_index: int
    transition: NFLPossessionTransition | None
    transition_index: int


@dataclass(frozen=True)
class _OTStartResult:
    plays: tuple[NFLRegularSeasonOTPlay, ...]
    next_play_index: int
    clock_remaining: int
    transition: NFLPossessionTransition
    transition_index: int
    completed_opportunity: NFLRegularSeasonOTOpportunity | None = None
    start_team: str | None = None
    start_yardline: int | None = None
    direct_continuation_team: str | None = None
    direct_continuation_yardline: int | None = None


class NFLRegularSeasonOTSimulator:
    """Seeded predictive Rule 16 simulator using shared A+C structural inputs."""

    def __init__(
        self,
        *,
        regulation_path: ResolvedFootballPath,
        home_profile: TeamDriveProfile,
        away_profile: TeamDriveProfile,
        home_field_position: NFLFieldPositionProfile | None = None,
        away_field_position: NFLFieldPositionProfile | None = None,
        home_return_scoring: NFLReturnScoringProfile | None = None,
        away_return_scoring: NFLReturnScoringProfile | None = None,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not isinstance(regulation_path, ResolvedFootballPath):
            raise TypeError("RESOLVED_REGULATION_PATH_REQUIRED")
        if not isinstance(home_profile, TeamDriveProfile) or not isinstance(away_profile, TeamDriveProfile):
            raise TypeError("TEAM_DRIVE_PROFILE_REQUIRED")
        if regulation_path.home_profile is None or regulation_path.away_profile is None:
            raise ValueError("OVERTIME_SPECIAL_TEAMS_PROFILES_REQUIRED")
        if (home_field_position is None) != (away_field_position is None):
            raise ValueError("OVERTIME_FIELD_POSITION_PROFILE_PAIR_REQUIRED")

        home = regulation_path.base_path.home_team
        away = regulation_path.base_path.away_team
        home_field = home_field_position or NFLFieldPositionProfile(home)
        away_field = away_field_position or NFLFieldPositionProfile(away)
        if not isinstance(home_field, NFLFieldPositionProfile) or not isinstance(away_field, NFLFieldPositionProfile):
            raise TypeError("NFL_FIELD_POSITION_PROFILE_REQUIRED")
        if home_field.team != home or away_field.team != away:
            raise ValueError("OVERTIME_FIELD_POSITION_TEAM_MISMATCH")

        home_return = home_return_scoring or NFLReturnScoringProfile(home)
        away_return = away_return_scoring or NFLReturnScoringProfile(away)
        if not isinstance(home_return, NFLReturnScoringProfile) or not isinstance(away_return, NFLReturnScoringProfile):
            raise TypeError("NFL_RETURN_SCORING_PROFILE_REQUIRED")
        if home_return.team != home or away_return.team != away:
            raise ValueError("OVERTIME_RETURN_SCORING_TEAM_MISMATCH")

        self.regulation_path = regulation_path
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.home_special = regulation_path.home_profile
        self.away_special = regulation_path.away_profile
        self.home_field_position = home_field
        self.away_field_position = away_field
        self.home_return_scoring = home_return
        self.away_return_scoring = away_return
        self.seed = int(seed)

        self._a_kernel = EngineADrivePlaySimulator(
            game_id=regulation_path.base_path.game_id,
            home_team=home,
            away_team=away,
            home_profile=home_profile,
            away_profile=away_profile,
            seed=self.seed,
        )
        self.rng = self._a_kernel.rng
        self._c_kernel = EngineCSpecialTeamsResolver(
            home_profile=self.home_special,
            away_profile=self.away_special,
            seed=self.seed,
        )
        self._returns = NFLReturnScoringResolver(
            home_return,
            away_return,
            seed=self.seed + 1,
        )
        self._field = NFLFieldPositionResolver(
            home_field,
            away_field,
            seed=self.seed + 2,
        )
        self._field_clock_rng = np.random.default_rng(self.seed + 3)

    def _drive_profile(self, team: str) -> TeamDriveProfile:
        if team == self.regulation_path.base_path.home_team:
            return self.home_profile
        if team == self.regulation_path.base_path.away_team:
            return self.away_profile
        raise ValueError("OVERTIME_TEAM_NOT_IN_GAME")

    def _special_profile(self, team: str) -> SpecialTeamsProfile:
        if team == self.regulation_path.base_path.home_team:
            return self.home_special
        if team == self.regulation_path.base_path.away_team:
            return self.away_special
        raise ValueError("OVERTIME_TEAM_NOT_IN_GAME")

    def _other(self, team: str) -> str:
        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        if team == home:
            return away
        if team == away:
            return home
        raise ValueError("OVERTIME_TEAM_NOT_IN_GAME")

    def _resolve_try(self, team: str, *, force_two: bool = False) -> tuple[int, str]:
        profile = self._special_profile(team)
        two_point = force_two or self.rng.random() < profile.two_point_attempt_rate
        if two_point:
            made = bool(self.rng.random() < profile.two_point_success_rate)
            return (2 if made else 0, "TWO_POINT_MADE" if made else "TWO_POINT_MISSED")
        self._c_kernel._require_kicker(profile)
        made = bool(self.rng.random() < self._c_kernel._xp_probability(profile))
        return (1 if made else 0, "XP_MADE" if made else "XP_MISSED")

    def _resolve_fg(self, team: str, distance: int) -> tuple[int, str]:
        profile = self._special_profile(team)
        self._c_kernel._require_kicker(profile)
        made = bool(self.rng.random() < self._c_kernel._fg_probability(profile, distance))
        return (3 if made else 0, "FG_MADE" if made else "FG_MISSED")

    @staticmethod
    def _scores(opportunities: list[NFLRegularSeasonOTOpportunity], home: str, away: str) -> dict[str, int]:
        out = {home: 0, away: 0}
        for item in opportunities:
            if item.points and item.scoring_team is not None:
                out[item.scoring_team] += item.points
        return out

    def _touchdown_try_points(
        self,
        *,
        team: str,
        opportunity_index: int,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
    ) -> tuple[int, str | None, str]:
        if clock_remaining == 0:
            return 0, None, "TOUCHDOWN_CLOCK_EXPIRED"
        if opportunity_index > 2:
            return 0, None, "TOUCHDOWN_SUDDEN_DEATH"

        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        if opportunity_index == 1:
            points, event = self._resolve_try(team)
            return points, event, "TOUCHDOWN_WITH_TRY"

        scores = self._scores(prior_opportunities, home, away)
        opponent = away if team == home else home
        raw_after_td = scores[team] + 6
        if raw_after_td > scores[opponent]:
            return 0, None, "TOUCHDOWN_SECOND_POSSESSION_WIN"

        force_two = scores[opponent] - raw_after_td == 2
        points, event = self._resolve_try(team, force_two=force_two)
        return points, event, "TOUCHDOWN_WITH_TRY"

    @staticmethod
    def _return_outcome(prefix: str, touchdown_outcome: str) -> str:
        suffix = touchdown_outcome.removeprefix("TOUCHDOWN_")
        return f"{prefix}_TOUCHDOWN_{suffix}"

    def _live_kick_duration(self, clock_remaining: int, *, onside: bool) -> int:
        if clock_remaining <= 0:
            return 0
        low, high = (3, 7) if onside else (5, 11)
        return min(clock_remaining, int(self._field_clock_rng.integers(low, high + 1)))

    def _resolve_kickoff_start(
        self,
        *,
        opportunity_index: int,
        kicking_team: str,
        receiving_team: str,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
        next_play_index: int,
        transition_index: int,
        label: str,
    ) -> _OTStartResult:
        transition = self._field.kickoff(
            transition_index=transition_index + 1,
            source_play_id=None,
            next_drive_id=opportunity_index,
            kicking_team=kicking_team,
            receiving_team=receiving_team,
            period=5,
            clock_seconds_remaining=clock_remaining,
            kicking_team_trailing=False,
            label=label,
            allow_onside=True,
        )
        transition_index = transition.transition_index
        plays: list[NFLRegularSeasonOTPlay] = []

        if "ONSIDE" in transition.transition_type:
            duration = self._live_kick_duration(clock_remaining, onside=True)
            clock_remaining -= duration
            transition = replace(transition, clock_seconds_remaining=clock_remaining)
            plays.append(
                NFLRegularSeasonOTPlay(
                    opportunity_index=opportunity_index,
                    play_index=next_play_index,
                    opportunity_team=receiving_team,
                    clock_end_seconds_remaining=clock_remaining,
                    down=1,
                    distance=10,
                    yardline_100=50,
                    play_type="ONSIDE_KICK",
                    yards=0,
                    transition_index=transition_index,
                )
            )
            next_play_index += 1
            if transition.next_possession_team == kicking_team:
                opportunity = NFLRegularSeasonOTOpportunity(
                    opportunity_index=opportunity_index,
                    opportunity_team=receiving_team,
                    scoring_team=None,
                    points=0,
                    clock_end_seconds_remaining=clock_remaining,
                    outcome_type="ONSIDE_RECOVERED_KICKING",
                )
                return _OTStartResult(
                    tuple(plays), next_play_index, clock_remaining, transition,
                    transition_index,
                    completed_opportunity=opportunity,
                    direct_continuation_team=kicking_team,
                    direct_continuation_yardline=transition.next_yardline_100,
                )
            if clock_remaining == 0:
                opportunity = NFLRegularSeasonOTOpportunity(
                    opportunity_index, receiving_team, None, 0, 0,
                    "CLOCK_EXPIRED_NO_SCORE",
                )
                return _OTStartResult(
                    tuple(plays), next_play_index, 0, transition,
                    transition_index, completed_opportunity=opportunity,
                )
            return _OTStartResult(
                tuple(plays), next_play_index, clock_remaining, transition,
                transition_index,
                start_team=receiving_team,
                start_yardline=transition.next_yardline_100,
            )

        if transition.transition_type.endswith("_RETURN"):
            duration = self._live_kick_duration(clock_remaining, onside=False)
            clock_remaining -= duration
            transition = replace(transition, clock_seconds_remaining=clock_remaining)
            return_td = self._returns.is_touchdown(receiving_team, "KICKOFF")
            try_points = 0
            try_event: str | None = None
            outcome = "NO_SCORE"
            if return_td:
                try_points, try_event, td_outcome = self._touchdown_try_points(
                    team=receiving_team,
                    opportunity_index=opportunity_index,
                    clock_remaining=clock_remaining,
                    prior_opportunities=prior_opportunities,
                )
                outcome = self._return_outcome("KICKOFF_RETURN", td_outcome)
                transition = replace(
                    transition,
                    transition_type=f"{transition.transition_type}_TD",
                    creates_next_drive=False,
                )
            plays.append(
                NFLRegularSeasonOTPlay(
                    opportunity_index=opportunity_index,
                    play_index=next_play_index,
                    opportunity_team=receiving_team,
                    clock_end_seconds_remaining=clock_remaining,
                    down=1,
                    distance=10,
                    yardline_100=100,
                    play_type="KICKOFF_RETURN",
                    yards=int(transition.return_yards or 0),
                    special_teams_points=try_points,
                    special_teams_event_type=try_event,
                    return_points=6 if return_td else 0,
                    return_scoring_team=receiving_team if return_td else None,
                    transition_index=transition_index,
                )
            )
            next_play_index += 1
            if return_td:
                opportunity = NFLRegularSeasonOTOpportunity(
                    opportunity_index=opportunity_index,
                    opportunity_team=receiving_team,
                    scoring_team=receiving_team,
                    points=6 + try_points,
                    clock_end_seconds_remaining=clock_remaining,
                    outcome_type=outcome,
                )
                return _OTStartResult(
                    tuple(plays), next_play_index, clock_remaining, transition,
                    transition_index, completed_opportunity=opportunity,
                )
            if clock_remaining == 0:
                opportunity = NFLRegularSeasonOTOpportunity(
                    opportunity_index, receiving_team, None, 0, 0,
                    "CLOCK_EXPIRED_NO_SCORE",
                )
                return _OTStartResult(
                    tuple(plays), next_play_index, 0, transition,
                    transition_index, completed_opportunity=opportunity,
                )

        return _OTStartResult(
            tuple(plays), next_play_index, clock_remaining, transition,
            transition_index,
            start_team=receiving_team,
            start_yardline=transition.next_yardline_100,
        )

    def _resolve_punt_transition(
        self,
        *,
        transition_index: int,
        source_play_index: int,
        punting_team: str,
        receiving_team: str,
        clock_remaining: int,
        kicking_yardline_100: int,
    ) -> NFLPossessionTransition:
        return self._field.punt(
            transition_index=transition_index + 1,
            source_play_id=source_play_index,
            next_drive_id=transition_index + 2,
            punting_team=punting_team,
            receiving_team=receiving_team,
            period=5,
            clock_seconds_remaining=clock_remaining,
            kicking_yardline_100=kicking_yardline_100,
        )

    def _start_from_transition(
        self,
        *,
        opportunity_index: int,
        transition: NFLPossessionTransition,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
        next_play_index: int,
    ) -> _OTStartResult:
        team = transition.next_possession_team
        plays: list[NFLRegularSeasonOTPlay] = []

        if transition.transition_type == "PUNT_RETURN":
            return_td = self._returns.is_touchdown(team, "PUNT")
            try_points = 0
            try_event: str | None = None
            outcome = "NO_SCORE"
            if return_td:
                try_points, try_event, td_outcome = self._touchdown_try_points(
                    team=team,
                    opportunity_index=opportunity_index,
                    clock_remaining=clock_remaining,
                    prior_opportunities=prior_opportunities,
                )
                outcome = self._return_outcome("PUNT_RETURN", td_outcome)
                transition = replace(
                    transition,
                    transition_type="PUNT_RETURN_TD",
                    creates_next_drive=False,
                )
            plays.append(
                NFLRegularSeasonOTPlay(
                    opportunity_index=opportunity_index,
                    play_index=next_play_index,
                    opportunity_team=team,
                    clock_end_seconds_remaining=clock_remaining,
                    down=1,
                    distance=10,
                    yardline_100=100,
                    play_type="PUNT_RETURN",
                    yards=max(0, 100 - transition.next_yardline_100),
                    special_teams_points=try_points,
                    special_teams_event_type=try_event,
                    return_points=6 if return_td else 0,
                    return_scoring_team=team if return_td else None,
                    transition_index=transition.transition_index,
                )
            )
            next_play_index += 1
            if return_td:
                opportunity = NFLRegularSeasonOTOpportunity(
                    opportunity_index=opportunity_index,
                    opportunity_team=team,
                    scoring_team=team,
                    points=6 + try_points,
                    clock_end_seconds_remaining=clock_remaining,
                    outcome_type=outcome,
                )
                return _OTStartResult(
                    tuple(plays), next_play_index, clock_remaining, transition,
                    transition.transition_index, completed_opportunity=opportunity,
                )

        if clock_remaining == 0:
            opportunity = NFLRegularSeasonOTOpportunity(
                opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
            )
            return _OTStartResult(
                tuple(plays), next_play_index, 0, transition,
                transition.transition_index, completed_opportunity=opportunity,
            )
        return _OTStartResult(
            tuple(plays), next_play_index, clock_remaining, transition,
            transition.transition_index,
            start_team=team,
            start_yardline=transition.next_yardline_100,
        )

    def _simulate_opportunity(
        self,
        *,
        opportunity_index: int,
        team: str,
        start_yardline: int,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
        next_play_index: int,
        transition_index: int,
    ) -> _OTDriveResult:
        profile = self._drive_profile(team)
        yardline = int(start_yardline)
        if not 1 <= yardline <= 99:
            raise ValueError("OVERTIME_START_YARDLINE_INVALID")
        down = 1
        distance = max(1, min(10, yardline))
        plays: list[NFLRegularSeasonOTPlay] = []
        play_index = next_play_index

        for _ in range(40):
            if clock_remaining <= 0:
                break

            if down == 4 and yardline <= 35 and self.rng.random() < profile.field_goal_attempt_rate:
                duration = min(clock_remaining, int(self.rng.integers(4, 9)))
                clock_remaining -= duration
                kick_distance = int(yardline + 17)
                st_points, st_event = self._resolve_fg(team, kick_distance)
                plays.append(
                    NFLRegularSeasonOTPlay(
                        opportunity_index, play_index, team, clock_remaining,
                        down, distance, yardline, "FIELD_GOAL", 0,
                        kick_distance=kick_distance,
                        special_teams_points=st_points,
                        special_teams_event_type=st_event,
                    )
                )
                source_index = play_index
                play_index += 1
                transition = None
                if not st_points and clock_remaining > 0:
                    transition = self._field.missed_field_goal(
                        transition_index=transition_index + 1,
                        source_play_id=source_index,
                        next_drive_id=opportunity_index + 1,
                        kicking_team=team,
                        receiving_team=self._other(team),
                        period=5,
                        clock_seconds_remaining=clock_remaining,
                        line_of_scrimmage_yardline_100=yardline,
                    )
                    transition_index = transition.transition_index
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=team if st_points else None,
                        points=st_points,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type="FIELD_GOAL" if st_points else "MISSED_FIELD_GOAL",
                    ),
                    tuple(plays), play_index, transition, transition_index,
                )

            if down == 4 and yardline > 60:
                duration = min(clock_remaining, int(self.rng.integers(6, 11)))
                clock_remaining -= duration
                source_index = play_index
                plays.append(
                    NFLRegularSeasonOTPlay(
                        opportunity_index, play_index, team, clock_remaining,
                        down, distance, yardline, "PUNT", 0,
                    )
                )
                play_index += 1
                transition = None
                if clock_remaining > 0:
                    transition = self._resolve_punt_transition(
                        transition_index=transition_index,
                        source_play_index=source_index,
                        punting_team=team,
                        receiving_team=self._other(team),
                        clock_remaining=clock_remaining,
                        kicking_yardline_100=yardline,
                    )
                    transition_index = transition.transition_index
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "PUNT"
                    ),
                    tuple(plays), play_index, transition, transition_index,
                )

            duration = min(clock_remaining, self._a_kernel._duration(profile))
            clock_remaining -= duration
            play_type = "PASS" if self.rng.random() < profile.pass_rate else "RUSH"

            if self.rng.random() < profile.turnover_rate:
                turnover_type = "INTERCEPTION" if play_type == "PASS" else "FUMBLE"
                pass_complete = False if play_type == "PASS" else None
                yards = 0 if play_type == "PASS" else self._a_kernel._regular_play_yards(profile, play_type)
                after_yardline = max(0, min(100, yardline - yards))
                defense = self._other(team)
                return_td = self._returns.is_touchdown(defense, "TURNOVER")
                defensive_points = 6 if return_td else 0
                source_index = play_index
                plays.append(
                    NFLRegularSeasonOTPlay(
                        opportunity_index, play_index, team, clock_remaining,
                        down, distance, yardline, play_type, yards,
                        pass_complete=pass_complete,
                        turnover_type=turnover_type,
                        defensive_points=defensive_points,
                        defensive_scoring_team=defense if return_td else None,
                    )
                )
                play_index += 1
                if return_td:
                    return _OTDriveResult(
                        NFLRegularSeasonOTOpportunity(
                            opportunity_index=opportunity_index,
                            opportunity_team=team,
                            scoring_team=defense,
                            points=6,
                            clock_end_seconds_remaining=clock_remaining,
                            outcome_type="DEFENSIVE_RETURN_TOUCHDOWN",
                        ),
                        tuple(plays), play_index, None, transition_index,
                    )
                transition = None
                if clock_remaining > 0:
                    transition = self._field.turnover(
                        transition_index=transition_index + 1,
                        source_play_id=source_index,
                        next_drive_id=opportunity_index + 1,
                        offense_team=team,
                        defense_team=defense,
                        period=5,
                        clock_seconds_remaining=clock_remaining,
                        offense_yardline_100_after_play=after_yardline,
                        transition_type=turnover_type,
                    )
                    transition_index = transition.transition_index
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "TURNOVER"
                    ),
                    tuple(plays), play_index, transition, transition_index,
                )

            if play_type == "PASS" and self.rng.random() < profile.sack_rate:
                play_type = "SACK"
                pass_complete = None
                yards = -int(self.rng.integers(1, 13))
            elif play_type == "PASS":
                pass_complete = bool(self.rng.random() < profile.completion_rate)
                yards = self._a_kernel._regular_play_yards(profile, play_type) if pass_complete else 0
            else:
                pass_complete = None
                yards = self._a_kernel._regular_play_yards(profile, play_type)

            raw_new_yardline = yardline - yards
            safety = raw_new_yardline >= 100 and yards < 0
            touchdown = raw_new_yardline <= 0 and (play_type != "PASS" or pass_complete)
            try_points = 0
            try_event: str | None = None
            outcome_type = "NO_SCORE"
            if touchdown:
                try_points, try_event, outcome_type = self._touchdown_try_points(
                    team=team,
                    opportunity_index=opportunity_index,
                    clock_remaining=clock_remaining,
                    prior_opportunities=prior_opportunities,
                )

            defense = self._other(team)
            defensive_points = 2 if safety else 0
            plays.append(
                NFLRegularSeasonOTPlay(
                    opportunity_index, play_index, team, clock_remaining,
                    down, distance, yardline, play_type, yards,
                    pass_complete=pass_complete,
                    raw_points=6 if touchdown else 0,
                    special_teams_points=try_points,
                    special_teams_event_type=try_event,
                    defensive_points=defensive_points,
                    defensive_scoring_team=defense if safety else None,
                )
            )
            play_index += 1

            if safety:
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=defense,
                        points=2,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type="KICKOFF_SAFETY" if opportunity_index == 1 else "SAFETY",
                    ),
                    tuple(plays), play_index, None, transition_index,
                )

            if touchdown:
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=team,
                        points=6 + try_points,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type=outcome_type,
                    ),
                    tuple(plays), play_index, None, transition_index,
                )

            if clock_remaining == 0:
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                    ),
                    tuple(plays), play_index, None, transition_index,
                )

            new_yardline = max(1, min(99, raw_new_yardline))
            converted = (pass_complete is True and yards >= distance) if play_type == "PASS" else yards >= distance
            yardline = new_yardline
            if converted:
                down = 1
                distance = max(1, min(10, yardline))
                continue
            if down == 4:
                transition = self._field.turnover(
                    transition_index=transition_index + 1,
                    source_play_id=play_index - 1,
                    next_drive_id=opportunity_index + 1,
                    offense_team=team,
                    defense_team=defense,
                    period=5,
                    clock_seconds_remaining=clock_remaining,
                    offense_yardline_100_after_play=yardline,
                    transition_type="TURNOVER_ON_DOWNS",
                )
                transition_index = transition.transition_index
                return _OTDriveResult(
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "TURNOVER_ON_DOWNS"
                    ),
                    tuple(plays), play_index, transition, transition_index,
                )
            distance = max(1, distance - yards)
            down += 1

        if clock_remaining == 0:
            return _OTDriveResult(
                NFLRegularSeasonOTOpportunity(
                    opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                ),
                tuple(plays), play_index, None, transition_index,
            )
        raise ValueError("OVERTIME_DRIVE_PLAY_LIMIT_EXCEEDED")

    def _terminal_result(
        self,
        *,
        plays: list[NFLRegularSeasonOTPlay],
        opportunities: list[NFLRegularSeasonOTOpportunity],
        transitions: list[NFLPossessionTransition],
        settlement: NFLRegularSeasonOvertimeResult,
    ) -> NFLRegularSeasonOTSimulation:
        result = NFLRegularSeasonOTSimulation(
            regulation_path=self.regulation_path,
            plays=tuple(plays),
            opportunities=tuple(opportunities),
            settlement=settlement,
            transitions=tuple(transitions),
        )
        result.assert_reconciliation()
        return result

    def _try_settlement(
        self,
        opportunities: list[NFLRegularSeasonOTOpportunity],
    ) -> NFLRegularSeasonOvertimeResult | None:
        try:
            return settle_nfl_regular_season_overtime(
                self.regulation_path,
                tuple(opportunities),
            )
        except ValueError as exc:
            if str(exc) not in _CONTINUATION_ERRORS:
                raise
            return None

    def simulate(self) -> NFLRegularSeasonOTSimulation:
        regulation = self.regulation_path.to_scoring_path().to_market_row()
        if regulation["home_score"] != regulation["away_score"]:
            raise ValueError("OVERTIME_REQUIRES_TIED_REGULATION")

        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        opening_receiver = home if self.rng.random() < 0.5 else away
        opening_kicker = self._other(opening_receiver)

        clock_remaining = 600
        next_play_index = 1
        transition_index = 0
        opportunity_index = 1
        opportunities: list[NFLRegularSeasonOTOpportunity] = []
        plays: list[NFLRegularSeasonOTPlay] = []
        transitions: list[NFLPossessionTransition] = []

        pending_kickoff: tuple[str, str, str] | None = (
            opening_kicker,
            opening_receiver,
            "OT_OPENING_KICKOFF",
        )
        pending_transition: NFLPossessionTransition | None = None
        direct_start: tuple[str, int] | None = None

        for _ in range(50):
            if opportunity_index > 35:
                raise ValueError("OVERTIME_OPPORTUNITY_LIMIT_EXCEEDED")

            start_team: str | None = None
            start_yardline: int | None = None

            if pending_kickoff is not None:
                kicking_team, receiving_team, label = pending_kickoff
                pending_kickoff = None
                start = self._resolve_kickoff_start(
                    opportunity_index=opportunity_index,
                    kicking_team=kicking_team,
                    receiving_team=receiving_team,
                    clock_remaining=clock_remaining,
                    prior_opportunities=opportunities,
                    next_play_index=next_play_index,
                    transition_index=transition_index,
                    label=label,
                )
                transitions.append(start.transition)
                plays.extend(start.plays)
                next_play_index = start.next_play_index
                transition_index = start.transition_index
                clock_remaining = start.clock_remaining

                if start.completed_opportunity is not None:
                    opportunities.append(start.completed_opportunity)
                    settlement = self._try_settlement(opportunities)
                    if settlement is not None:
                        return self._terminal_result(
                            plays=plays,
                            opportunities=opportunities,
                            transitions=transitions,
                            settlement=settlement,
                        )
                    opportunity_index += 1
                    if start.direct_continuation_team is not None:
                        direct_start = (
                            start.direct_continuation_team,
                            int(start.direct_continuation_yardline),
                        )
                    elif start.completed_opportunity.scoring_team is not None:
                        scorer = start.completed_opportunity.scoring_team
                        pending_kickoff = (scorer, self._other(scorer), "OT_KICKOFF")
                    else:
                        raise ValueError("OVERTIME_KICK_COMPLETION_CONTINUATION_UNRESOLVED")
                    continue

                start_team = start.start_team
                start_yardline = start.start_yardline

            elif pending_transition is not None:
                transition = pending_transition
                pending_transition = None
                start = self._start_from_transition(
                    opportunity_index=opportunity_index,
                    transition=transition,
                    clock_remaining=clock_remaining,
                    prior_opportunities=opportunities,
                    next_play_index=next_play_index,
                )
                if start.transition != transition:
                    # A punt-return touchdown changes only score/drive ownership;
                    # it retains the same transition identity and index.
                    transitions[-1] = start.transition
                plays.extend(start.plays)
                next_play_index = start.next_play_index
                clock_remaining = start.clock_remaining
                if start.completed_opportunity is not None:
                    opportunities.append(start.completed_opportunity)
                    settlement = self._try_settlement(opportunities)
                    if settlement is not None:
                        return self._terminal_result(
                            plays=plays,
                            opportunities=opportunities,
                            transitions=transitions,
                            settlement=settlement,
                        )
                    opportunity_index += 1
                    scorer = start.completed_opportunity.scoring_team
                    if scorer is None:
                        raise ValueError("OVERTIME_RETURN_SCORE_CONTINUATION_UNRESOLVED")
                    pending_kickoff = (scorer, self._other(scorer), "OT_KICKOFF")
                    continue
                start_team = start.start_team
                start_yardline = start.start_yardline

            elif direct_start is not None:
                start_team, start_yardline = direct_start
                direct_start = None
            else:
                raise ValueError("OVERTIME_START_STATE_REQUIRED")

            if start_team is None or start_yardline is None:
                raise ValueError("OVERTIME_DRIVE_START_UNRESOLVED")

            drive = self._simulate_opportunity(
                opportunity_index=opportunity_index,
                team=start_team,
                start_yardline=start_yardline,
                clock_remaining=clock_remaining,
                prior_opportunities=opportunities,
                next_play_index=next_play_index,
                transition_index=transition_index,
            )
            plays.extend(drive.plays)
            opportunities.append(drive.opportunity)
            next_play_index = drive.next_play_index
            clock_remaining = drive.opportunity.clock_end_seconds_remaining
            transition_index = drive.transition_index
            if drive.transition is not None:
                transitions.append(drive.transition)

            settlement = self._try_settlement(opportunities)
            if settlement is not None:
                return self._terminal_result(
                    plays=plays,
                    opportunities=opportunities,
                    transitions=transitions,
                    settlement=settlement,
                )

            opportunity_index += 1
            if drive.transition is not None:
                pending_transition = drive.transition
                continue
            if drive.opportunity.scoring_team is not None:
                scorer = drive.opportunity.scoring_team
                # Defensive return TDs and safeties are terminal under the Rule
                # 16 states this simulator emits; reaching here would be corrupt.
                if scorer != drive.opportunity.opportunity_team:
                    raise ValueError("OVERTIME_DEFENSIVE_SCORE_CONTINUED_AFTER_SETTLEMENT")
                pending_kickoff = (scorer, self._other(scorer), "OT_KICKOFF")
                continue
            raise ValueError("OVERTIME_CONTINUATION_TRANSITION_MISSING")

        raise ValueError("OVERTIME_STATE_LOOP_LIMIT_EXCEEDED")
