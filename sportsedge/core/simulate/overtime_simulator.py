"""Predictive NFL regular-season overtime over shared Engine A+C primitives.

The simulator extends a tied resolved regulation path. Scrimmage opportunities
advance clock, down, distance, field position and play type with the same A play
kernel used in regulation; field goals and post-TD tries use the same C kick
probabilities. Sacks, safeties and turnover-return touchdowns are therefore real
path events rather than independent market draws.

Opening/score kickoffs and punt-return touchdown geometry are not yet integrated
into this OT generator and remain explicit full-game special-teams validation
blockers. They are not assigned a synthetic rate inside market read-outs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .drive_play import EngineADrivePlaySimulator, TeamDriveProfile
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
        if self.defensive_points > 0 and self.raw_points > 0:
            raise ValueError("OT_OFFENSIVE_DEFENSIVE_SCORE_COLLISION")
        if self.defensive_points == 6:
            if self.turnover_type not in {"INTERCEPTION", "FUMBLE"}:
                raise ValueError("OT_DEFENSIVE_RETURN_TD_REQUIRES_TURNOVER")
            if self.defensive_scoring_team == self.opportunity_team:
                raise ValueError("OT_DEFENSIVE_RETURN_TD_TEAM_INVALID")


@dataclass(frozen=True)
class NFLRegularSeasonOTSimulation:
    regulation_path: ResolvedFootballPath
    plays: tuple[NFLRegularSeasonOTPlay, ...]
    opportunities: tuple[NFLRegularSeasonOTOpportunity, ...]
    settlement: NFLRegularSeasonOvertimeResult

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

    def assert_reconciliation(self) -> None:
        for opportunity in self.opportunities:
            points = sum(
                play.raw_points + play.special_teams_points + play.defensive_points
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


class NFLRegularSeasonOTSimulator:
    """Seeded predictive Rule 16 simulator using shared A+C structural inputs."""

    def __init__(
        self,
        *,
        regulation_path: ResolvedFootballPath,
        home_profile: TeamDriveProfile,
        away_profile: TeamDriveProfile,
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

        home = regulation_path.base_path.home_team
        away = regulation_path.base_path.away_team
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

    def _simulate_opportunity(
        self,
        *,
        opportunity_index: int,
        team: str,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
        next_play_index: int,
    ) -> tuple[NFLRegularSeasonOTOpportunity, list[NFLRegularSeasonOTPlay], int]:
        profile = self._drive_profile(team)
        yardline = 75
        down = 1
        distance = 10
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
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=team if st_points else None,
                        points=st_points,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type="FIELD_GOAL" if st_points else "MISSED_FIELD_GOAL",
                    ),
                    plays,
                    play_index + 1,
                )

            if down == 4 and yardline > 60:
                duration = min(clock_remaining, int(self.rng.integers(6, 11)))
                clock_remaining -= duration
                plays.append(
                    NFLRegularSeasonOTPlay(
                        opportunity_index, play_index, team, clock_remaining,
                        down, distance, yardline, "PUNT", 0,
                    )
                )
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "PUNT"
                    ),
                    plays,
                    play_index + 1,
                )

            duration = min(clock_remaining, self._a_kernel._duration(profile))
            clock_remaining -= duration
            play_type = "PASS" if self.rng.random() < profile.pass_rate else "RUSH"

            if self.rng.random() < profile.turnover_rate:
                turnover_type = "INTERCEPTION" if play_type == "PASS" else "FUMBLE"
                pass_complete = False if play_type == "PASS" else None
                yards = 0 if play_type == "PASS" else self._a_kernel._regular_play_yards(profile, play_type)
                defense = self._other(team)
                return_td = self._returns.is_touchdown(defense, "TURNOVER")
                defensive_points = 6 if return_td else 0
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
                if return_td:
                    return (
                        NFLRegularSeasonOTOpportunity(
                            opportunity_index=opportunity_index,
                            opportunity_team=team,
                            scoring_team=defense,
                            points=6,
                            clock_end_seconds_remaining=clock_remaining,
                            outcome_type="DEFENSIVE_RETURN_TOUCHDOWN",
                        ),
                        plays,
                        play_index + 1,
                    )
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "TURNOVER"
                    ),
                    plays,
                    play_index + 1,
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
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=defense,
                        points=2,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type="KICKOFF_SAFETY" if opportunity_index == 1 else "SAFETY",
                    ),
                    plays,
                    play_index,
                )

            if touchdown:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index=opportunity_index,
                        opportunity_team=team,
                        scoring_team=team,
                        points=6 + try_points,
                        clock_end_seconds_remaining=clock_remaining,
                        outcome_type=outcome_type,
                    ),
                    plays,
                    play_index,
                )

            if clock_remaining == 0:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                    ),
                    plays,
                    play_index,
                )

            new_yardline = max(1, min(99, raw_new_yardline))
            converted = (pass_complete is True and yards >= distance) if play_type == "PASS" else yards >= distance
            yardline = new_yardline
            if converted:
                down = 1
                distance = max(1, min(10, yardline))
                continue
            if down == 4:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "TURNOVER_ON_DOWNS"
                    ),
                    plays,
                    play_index,
                )
            distance = max(1, distance - yards)
            down += 1

        if clock_remaining == 0:
            return (
                NFLRegularSeasonOTOpportunity(
                    opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                ),
                plays,
                play_index,
            )
        raise ValueError("OVERTIME_DRIVE_PLAY_LIMIT_EXCEEDED")

    def simulate(self) -> NFLRegularSeasonOTSimulation:
        regulation = self.regulation_path.to_scoring_path().to_market_row()
        if regulation["home_score"] != regulation["away_score"]:
            raise ValueError("OVERTIME_REQUIRES_TIED_REGULATION")

        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        team = home if self.rng.random() < 0.5 else away
        clock_remaining = 600
        next_play_index = 1
        opportunities: list[NFLRegularSeasonOTOpportunity] = []
        plays: list[NFLRegularSeasonOTPlay] = []

        for opportunity_index in range(1, 35):
            opportunity, new_plays, next_play_index = self._simulate_opportunity(
                opportunity_index=opportunity_index,
                team=team,
                clock_remaining=clock_remaining,
                prior_opportunities=opportunities,
                next_play_index=next_play_index,
            )
            opportunities.append(opportunity)
            plays.extend(new_plays)
            clock_remaining = opportunity.clock_end_seconds_remaining

            try:
                settlement = settle_nfl_regular_season_overtime(
                    self.regulation_path,
                    tuple(opportunities),
                )
            except ValueError as exc:
                if str(exc) not in _CONTINUATION_ERRORS:
                    raise
            else:
                result = NFLRegularSeasonOTSimulation(
                    regulation_path=self.regulation_path,
                    plays=tuple(plays),
                    opportunities=tuple(opportunities),
                    settlement=settlement,
                )
                result.assert_reconciliation()
                return result

            team = away if team == home else home

        raise ValueError("OVERTIME_OPPORTUNITY_LIMIT_EXCEEDED")
