"""Full 2026 NFL regular-season overtime over A+B/C transition primitives.

This wrapper composes the existing scrimmage OT kernel with period-5 kickoff and
punt transitions. It preserves Rule 16 possession credit when possession changes
on a return and makes the resulting field position feed the next scrimmage path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .field_position import NFLFieldPositionProfile
from .football_path import FootballGamePath
from .overtime import (
    NFLRegularSeasonOTOpportunity,
    NFLRegularSeasonOvertimeResult,
    settle_nfl_regular_season_overtime,
)
from .overtime_simulator import (
    NFLRegularSeasonOTPlay,
    NFLRegularSeasonOTSimulator,
)
from .overtime_transitions import (
    NFLRegularSeasonOTTransition,
    NFLRegularSeasonOTTransitionResolver,
)
from .return_scoring import NFLReturnScoringProfile
from .special_teams import ResolvedFootballPath
from .drive_play import TeamDriveProfile


_CONTINUATION_ERRORS = {
    "OVERTIME_SECOND_OPPORTUNITY_REQUIRED",
    "OVERTIME_SUDDEN_DEATH_CONTINUATION_REQUIRED",
}


@dataclass(frozen=True)
class NFLRegularSeasonFullOTSimulation:
    regulation_path: ResolvedFootballPath
    plays: tuple[NFLRegularSeasonOTPlay, ...]
    transitions: tuple[NFLRegularSeasonOTTransition, ...]
    opportunities: tuple[NFLRegularSeasonOTOpportunity, ...]
    settlement: NFLRegularSeasonOvertimeResult

    def assert_reconciliation(self) -> None:
        for opportunity in self.opportunities:
            play_points = sum(
                play.raw_points + play.special_teams_points + play.defensive_points
                for play in self.plays
                if play.opportunity_index == opportunity.opportunity_index
            )
            transition_points = sum(
                transition.points
                for transition in self.transitions
                if transition.opportunity_index == opportunity.opportunity_index
            )
            if play_points + transition_points != opportunity.points:
                raise ValueError("FULL_OT_OPPORTUNITY_SCORE_RECONCILIATION_FAILED")

        scoring = self.settlement.to_scoring_path().to_market_row()
        regulation = self.regulation_path.to_scoring_path().to_market_row()
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
        if scoring["home_score"] - regulation["home_score"] != expected_home:
            raise ValueError("FULL_OT_HOME_SCORE_RECONCILIATION_FAILED")
        if scoring["away_score"] - regulation["away_score"] != expected_away:
            raise ValueError("FULL_OT_AWAY_SCORE_RECONCILIATION_FAILED")

        clocks = [transition.clock_seconds_remaining for transition in self.transitions]
        if clocks != sorted(clocks, reverse=True):
            raise ValueError("FULL_OT_TRANSITION_CLOCK_ORDER_INVALID")

    def to_scoring_path(self) -> FootballGamePath:
        self.assert_reconciliation()
        return self.settlement.to_scoring_path()


class NFLRegularSeasonFullOTSimulator(NFLRegularSeasonOTSimulator):
    """Rule 16 simulator with opening-kick and punt-return possession geometry."""

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
        super().__init__(
            regulation_path=regulation_path,
            home_profile=home_profile,
            away_profile=away_profile,
            home_return_scoring=home_return_scoring,
            away_return_scoring=away_return_scoring,
            seed=seed,
        )
        home = regulation_path.base_path.home_team
        away = regulation_path.base_path.away_team
        self.home_field_position = home_field_position or NFLFieldPositionProfile(home)
        self.away_field_position = away_field_position or NFLFieldPositionProfile(away)
        if self.home_field_position.team != home or self.away_field_position.team != away:
            raise ValueError("FULL_OT_FIELD_POSITION_TEAM_MISMATCH")
        self._ot_transitions = NFLRegularSeasonOTTransitionResolver(
            self.home_field_position,
            self.away_field_position,
            self.home_return_scoring,
            self.away_return_scoring,
            seed=self.seed + 2,
        )

    def _simulate_scrimmage_opportunity(
        self,
        *,
        opportunity_index: int,
        team: str,
        clock_remaining: int,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
        next_play_index: int,
        start_yardline_100: int,
        next_transition_index: int,
    ) -> tuple[
        NFLRegularSeasonOTOpportunity,
        list[NFLRegularSeasonOTPlay],
        int,
        NFLRegularSeasonOTTransition | None,
        int,
    ]:
        profile = self._drive_profile(team)
        yardline = int(start_yardline_100)
        if not 1 <= yardline <= 99:
            raise ValueError("FULL_OT_START_YARDLINE_INVALID")
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
                plays.append(NFLRegularSeasonOTPlay(
                    opportunity_index, play_index, team, clock_remaining,
                    down, distance, yardline, "FIELD_GOAL", 0,
                    kick_distance=kick_distance,
                    special_teams_points=st_points,
                    special_teams_event_type=st_event,
                ))
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, team if st_points else None,
                        st_points, clock_remaining,
                        "FIELD_GOAL" if st_points else "MISSED_FIELD_GOAL",
                    ),
                    plays, play_index + 1, None, next_transition_index,
                )

            if down == 4 and yardline > 60:
                receiver = self._other(team)
                transition = self._ot_transitions.punt(
                    transition_index=next_transition_index,
                    opportunity_index=opportunity_index + 1,
                    punting_team=team,
                    receiving_team=receiver,
                    clock_seconds_remaining=clock_remaining,
                    kicking_yardline_100=yardline,
                )
                clock_remaining = transition.clock_seconds_remaining
                plays.append(NFLRegularSeasonOTPlay(
                    opportunity_index, play_index, team, clock_remaining,
                    down, distance, yardline, "PUNT", 0,
                ))
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "PUNT"
                    ),
                    plays, play_index + 1, transition, next_transition_index + 1,
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
                plays.append(NFLRegularSeasonOTPlay(
                    opportunity_index, play_index, team, clock_remaining,
                    down, distance, yardline, play_type, yards,
                    pass_complete=pass_complete,
                    turnover_type=turnover_type,
                    defensive_points=defensive_points,
                    defensive_scoring_team=defense if return_td else None,
                ))
                if return_td:
                    return (
                        NFLRegularSeasonOTOpportunity(
                            opportunity_index, team, defense, 6, clock_remaining,
                            "DEFENSIVE_RETURN_TOUCHDOWN",
                        ),
                        plays, play_index + 1, None, next_transition_index,
                    )
                after_yardline = max(0, min(100, yardline - yards))
                next_spot = max(1, min(99, 100 - after_yardline))
                transition = NFLRegularSeasonOTTransition(
                    transition_index=next_transition_index,
                    transition_type=turnover_type,
                    from_team=team,
                    receiving_team=defense,
                    next_possession_team=defense,
                    next_yardline_100=next_spot,
                    clock_seconds_remaining=clock_remaining,
                    opportunity_index=opportunity_index + 1,
                )
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining, "TURNOVER"
                    ),
                    plays, play_index + 1, transition, next_transition_index + 1,
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
            plays.append(NFLRegularSeasonOTPlay(
                opportunity_index, play_index, team, clock_remaining,
                down, distance, yardline, play_type, yards,
                pass_complete=pass_complete,
                raw_points=6 if touchdown else 0,
                special_teams_points=try_points,
                special_teams_event_type=try_event,
                defensive_points=defensive_points,
                defensive_scoring_team=defense if safety else None,
            ))
            play_index += 1

            if safety:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, defense, 2, clock_remaining,
                        "KICKOFF_SAFETY" if opportunity_index == 1 else "SAFETY",
                    ),
                    plays, play_index, None, next_transition_index,
                )
            if touchdown:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, team, 6 + try_points,
                        clock_remaining, outcome_type,
                    ),
                    plays, play_index, None, next_transition_index,
                )
            if clock_remaining == 0:
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                    ),
                    plays, play_index, None, next_transition_index,
                )

            new_yardline = max(1, min(99, raw_new_yardline))
            converted = (pass_complete is True and yards >= distance) if play_type == "PASS" else yards >= distance
            yardline = new_yardline
            if converted:
                down = 1
                distance = max(1, min(10, yardline))
                continue
            if down == 4:
                defense = self._other(team)
                transition = NFLRegularSeasonOTTransition(
                    transition_index=next_transition_index,
                    transition_type="TURNOVER_ON_DOWNS",
                    from_team=team,
                    receiving_team=defense,
                    next_possession_team=defense,
                    next_yardline_100=max(1, min(99, 100 - yardline)),
                    clock_seconds_remaining=clock_remaining,
                    opportunity_index=opportunity_index + 1,
                )
                return (
                    NFLRegularSeasonOTOpportunity(
                        opportunity_index, team, None, 0, clock_remaining,
                        "TURNOVER_ON_DOWNS",
                    ),
                    plays, play_index, transition, next_transition_index + 1,
                )
            distance = max(1, distance - yards)
            down += 1

        if clock_remaining == 0:
            return (
                NFLRegularSeasonOTOpportunity(
                    opportunity_index, team, None, 0, 0, "CLOCK_EXPIRED_NO_SCORE"
                ),
                plays, play_index, None, next_transition_index,
            )
        raise ValueError("FULL_OT_DRIVE_PLAY_LIMIT_EXCEEDED")

    def simulate(self) -> NFLRegularSeasonFullOTSimulation:
        regulation = self.regulation_path.to_scoring_path().to_market_row()
        if regulation["home_score"] != regulation["away_score"]:
            raise ValueError("OVERTIME_REQUIRES_TIED_REGULATION")

        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        receiver = home if self.rng.random() < 0.5 else away
        kicker = away if receiver == home else home
        next_transition_index = 1
        opening = self._ot_transitions.opening_kickoff(
            transition_index=next_transition_index,
            opportunity_index=1,
            kicking_team=kicker,
            receiving_team=receiver,
            clock_seconds_remaining=600,
        )
        next_transition_index += 1
        transitions: list[NFLRegularSeasonOTTransition] = [opening]
        opportunities: list[NFLRegularSeasonOTOpportunity] = []
        plays: list[NFLRegularSeasonOTPlay] = []
        next_play_index = 1
        opportunity_index = 1

        if opening.return_touchdown:
            try_points, _, _ = self._touchdown_try_points(
                team=receiver,
                opportunity_index=1,
                clock_remaining=opening.clock_seconds_remaining,
                prior_opportunities=[],
            )
            opening = opening.with_points(6 + try_points, scoring_team=receiver)
            transitions[0] = opening
            opportunities.append(NFLRegularSeasonOTOpportunity(
                1, receiver, receiver, 6 + try_points,
                opening.clock_seconds_remaining,
                "OPENING_KICKOFF_RETURN_TOUCHDOWN",
            ))
            clock_remaining = opening.clock_seconds_remaining
            next_team = kicker
            next_yardline = 75
            opportunity_index = 2
        else:
            assert opening.next_yardline_100 is not None
            clock_remaining = opening.clock_seconds_remaining
            next_team = receiver
            next_yardline = opening.next_yardline_100

        for _ in range(34):
            if opportunities:
                try:
                    settlement = settle_nfl_regular_season_overtime(
                        self.regulation_path, tuple(opportunities)
                    )
                except ValueError as exc:
                    if str(exc) not in _CONTINUATION_ERRORS:
                        raise
                else:
                    result = NFLRegularSeasonFullOTSimulation(
                        self.regulation_path, tuple(plays), tuple(transitions),
                        tuple(opportunities), settlement,
                    )
                    result.assert_reconciliation()
                    return result

            opportunity, new_plays, next_play_index, transition, next_transition_index = self._simulate_scrimmage_opportunity(
                opportunity_index=opportunity_index,
                team=next_team,
                clock_remaining=clock_remaining,
                prior_opportunities=opportunities,
                next_play_index=next_play_index,
                start_yardline_100=next_yardline,
                next_transition_index=next_transition_index,
            )
            opportunities.append(opportunity)
            plays.extend(new_plays)
            clock_remaining = opportunity.clock_end_seconds_remaining

            if transition is None:
                opportunity_index += 1
                next_team = self._other(next_team)
                next_yardline = 75
                continue

            transitions.append(transition)
            clock_remaining = transition.clock_seconds_remaining
            if transition.return_touchdown:
                receiving = transition.receiving_team
                next_opp_index = opportunity_index + 1
                try_points, _, _ = self._touchdown_try_points(
                    team=receiving,
                    opportunity_index=next_opp_index,
                    clock_remaining=clock_remaining,
                    prior_opportunities=opportunities,
                )
                transition = transition.with_points(6 + try_points, scoring_team=receiving)
                transitions[-1] = transition
                opportunities.append(NFLRegularSeasonOTOpportunity(
                    next_opp_index,
                    receiving,
                    receiving,
                    6 + try_points,
                    clock_remaining,
                    transition.transition_type,
                ))
                opportunity_index = next_opp_index + 1
                next_team = self._other(receiving)
                next_yardline = 75
            else:
                assert transition.next_yardline_100 is not None
                opportunity_index += 1
                next_team = transition.next_possession_team
                next_yardline = transition.next_yardline_100

        raise ValueError("FULL_OT_OPPORTUNITY_LIMIT_EXCEEDED")
