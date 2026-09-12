"""Integrated NFL regulation simulator over shared Engine A+C state.

This path consumes Engine C possession transitions between drives. Opening and
halftime kickoffs, score kickoffs, punts, missed field goals, turnovers, return
scores and safety kicks therefore alter the same game state used for ML/spread/
total and player/team read-outs.

Engine A owns scrimmage outcomes, raw offensive/defensive turnover-return TDs and
safeties. Engine C owns field goals, post-TD tries, kickoff/punt return TDs and
all kick/return possession transitions. A separate resolved score is carried
during generation so score-dependent rules use the true A+C score.

Numerical drive, return, special-teams and field-position inputs remain structural
candidates until fitted from point-in-time historical data. Penalties, timeouts
and detailed safety-kick recovery geometry remain explicit validation blockers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .drive_play import EngineADrivePlaySimulator, FootballPlayPath, PlayEvent, TeamDriveProfile
from .field_position import (
    NFLFieldPositionProfile,
    NFLFieldPositionResolver,
    NFLPossessionTransition,
)
from .return_scoring import (
    NFLReturnScoringProfile,
    NFLReturnScoringResolver,
)
from .special_teams import (
    EngineCSpecialTeamsResolver,
    ResolvedFootballPath,
    SpecialTeamsEvent,
    SpecialTeamsProfile,
)


@dataclass(frozen=True)
class NFLIntegratedRegulationSimulation:
    raw_path: FootballPlayPath
    resolved_path: ResolvedFootballPath
    transitions: tuple[NFLPossessionTransition, ...]
    final_home_score: int
    final_away_score: int
    opening_receiving_team: str
    second_half_receiving_team: str

    def __post_init__(self) -> None:
        if self.resolved_path.base_path != self.raw_path:
            raise ValueError("INTEGRATED_RESOLVED_RAW_PATH_MISMATCH")
        if self.opening_receiving_team not in {self.raw_path.home_team, self.raw_path.away_team}:
            raise ValueError("INTEGRATED_OPENING_RECEIVER_INVALID")
        if self.second_half_receiving_team not in {self.raw_path.home_team, self.raw_path.away_team}:
            raise ValueError("INTEGRATED_SECOND_HALF_RECEIVER_INVALID")
        if self.opening_receiving_team == self.second_half_receiving_team:
            raise ValueError("INTEGRATED_HALF_RECEIVER_NOT_ALTERNATED")
        if self.final_home_score < 0 or self.final_away_score < 0:
            raise ValueError("INTEGRATED_FINAL_SCORE_INVALID")

    def assert_reconciliation(self) -> None:
        self.raw_path.assert_reconciliation()
        self.resolved_path.assert_reconciliation()
        resolved = self.resolved_path.to_scoring_path().to_market_row()
        if resolved["home_score"] != self.final_home_score:
            raise ValueError("INTEGRATED_HOME_SCORE_RECONCILIATION_FAILED")
        if resolved["away_score"] != self.final_away_score:
            raise ValueError("INTEGRATED_AWAY_SCORE_RECONCILIATION_FAILED")

        indexes = [transition.transition_index for transition in self.transitions]
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("INTEGRATED_TRANSITION_INDEX_SEQUENCE_INVALID")

        first_by_drive: dict[int, PlayEvent] = {}
        for play in self.raw_path.plays:
            first_by_drive.setdefault(play.drive_id, play)
        for transition in self.transitions:
            if not transition.creates_next_drive:
                continue
            first = first_by_drive.get(transition.next_drive_id)
            if first is None:
                raise ValueError("INTEGRATED_TRANSITION_WITHOUT_NEXT_DRIVE")
            if first.possession != transition.next_possession_team:
                raise ValueError("INTEGRATED_TRANSITION_POSSESSION_MISMATCH")
            if first.yardline_100 != transition.next_yardline_100:
                raise ValueError("INTEGRATED_TRANSITION_YARDLINE_MISMATCH")

        opening = [t for t in self.transitions if t.transition_type.startswith("OPENING_KICKOFF")]
        halftime = [t for t in self.transitions if t.transition_type.startswith("HALFTIME_KICKOFF")]
        if len(opening) != 1:
            raise ValueError("INTEGRATED_OPENING_KICKOFF_COUNT_INVALID")
        if len(halftime) != 1:
            raise ValueError("INTEGRATED_HALFTIME_KICKOFF_COUNT_INVALID")
        if opening[0].next_possession_team != self.opening_receiving_team:
            raise ValueError("INTEGRATED_OPENING_RECEIVER_MISMATCH")
        if halftime[0].next_possession_team != self.second_half_receiving_team:
            raise ValueError("INTEGRATED_HALFTIME_RECEIVER_MISMATCH")

        scoring_transition_ids = {
            event.source_transition_index
            for event in self.resolved_path.special_teams_events
            if event.event_type in {"KICKOFF_RETURN_TD", "PUNT_RETURN_TD"}
        }
        for transition in self.transitions:
            if transition.transition_index in scoring_transition_ids and transition.creates_next_drive:
                raise ValueError("SCORING_RETURN_TRANSITION_CANNOT_CREATE_DRIVE")
        transition_ids = {transition.transition_index for transition in self.transitions}
        if not scoring_transition_ids.issubset(transition_ids):
            raise ValueError("RETURN_TD_EVENT_TRANSITION_NOT_FOUND")


class NFLIntegratedRegulationSimulator:
    """Seeded market-blind regulation path with drive-to-drive A+C transitions."""

    def __init__(
        self,
        *,
        game_id: str,
        home_team: str,
        away_team: str,
        home_profile: TeamDriveProfile,
        away_profile: TeamDriveProfile,
        home_special_teams: SpecialTeamsProfile,
        away_special_teams: SpecialTeamsProfile,
        home_field_position: NFLFieldPositionProfile,
        away_field_position: NFLFieldPositionProfile,
        home_return_scoring: NFLReturnScoringProfile | None = None,
        away_return_scoring: NFLReturnScoringProfile | None = None,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if not game_id:
            raise ValueError("GAME_ID_REQUIRED")
        if not home_team or not away_team or home_team == away_team:
            raise ValueError("INVALID_TEAM_IDENTITY")
        if not isinstance(home_profile, TeamDriveProfile) or not isinstance(away_profile, TeamDriveProfile):
            raise TypeError("TEAM_DRIVE_PROFILE_REQUIRED")
        if not isinstance(home_special_teams, SpecialTeamsProfile) or not isinstance(away_special_teams, SpecialTeamsProfile):
            raise TypeError("SPECIAL_TEAMS_PROFILE_REQUIRED")
        if not isinstance(home_field_position, NFLFieldPositionProfile) or not isinstance(away_field_position, NFLFieldPositionProfile):
            raise TypeError("NFL_FIELD_POSITION_PROFILE_REQUIRED")
        if home_special_teams.team != home_team or away_special_teams.team != away_team:
            raise ValueError("INTEGRATED_SPECIAL_TEAMS_TEAM_MISMATCH")
        if home_field_position.team != home_team or away_field_position.team != away_team:
            raise ValueError("INTEGRATED_FIELD_POSITION_TEAM_MISMATCH")

        home_return = home_return_scoring or NFLReturnScoringProfile(home_team)
        away_return = away_return_scoring or NFLReturnScoringProfile(away_team)
        if not isinstance(home_return, NFLReturnScoringProfile) or not isinstance(away_return, NFLReturnScoringProfile):
            raise TypeError("NFL_RETURN_SCORING_PROFILE_REQUIRED")
        if home_return.team != home_team or away_return.team != away_team:
            raise ValueError("INTEGRATED_RETURN_SCORING_TEAM_MISMATCH")

        self.game_id = game_id
        self.home_team = home_team
        self.away_team = away_team
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.home_special_teams = home_special_teams
        self.away_special_teams = away_special_teams
        self.home_field_position = home_field_position
        self.away_field_position = away_field_position
        self.home_return_scoring = home_return
        self.away_return_scoring = away_return
        self.seed = int(seed)

        self._a_kernel = EngineADrivePlaySimulator(
            game_id=game_id,
            home_team=home_team,
            away_team=away_team,
            home_profile=home_profile,
            away_profile=away_profile,
            seed=self.seed,
        )
        self.rng = self._a_kernel.rng
        self._c_kernel = EngineCSpecialTeamsResolver(
            home_profile=home_special_teams,
            away_profile=away_special_teams,
            seed=self.seed + 1,
        )
        self._field = NFLFieldPositionResolver(
            home_field_position,
            away_field_position,
            seed=self.seed + 2,
        )
        self._returns = NFLReturnScoringResolver(
            home_return,
            away_return,
            seed=self.seed + 3,
        )

    def _other(self, team: str) -> str:
        if team == self.home_team:
            return self.away_team
        if team == self.away_team:
            return self.home_team
        raise ValueError("TEAM_NOT_IN_GAME")

    def _drive_profile(self, team: str) -> TeamDriveProfile:
        return self.home_profile if team == self.home_team else self.away_profile

    def _special_profile(self, team: str) -> SpecialTeamsProfile:
        return self.home_special_teams if team == self.home_team else self.away_special_teams

    @staticmethod
    def _play_end_period_clock(remaining: int) -> tuple[int, int]:
        remaining = max(0, min(3600, int(remaining)))
        if remaining == 0:
            return 4, 0
        if remaining in (2700, 1800, 900):
            return int((3600 - remaining) // 900), 0
        elapsed = 3600 - remaining
        return int(elapsed // 900 + 1), int(900 - (elapsed % 900))

    @staticmethod
    def _transition_period_clock(remaining: int) -> tuple[int, int]:
        remaining = max(0, min(3600, int(remaining)))
        if remaining == 3600:
            return 1, 900
        if remaining == 2700:
            return 2, 900
        if remaining == 1800:
            return 3, 900
        if remaining == 900:
            return 4, 900
        if remaining == 0:
            return 4, 0
        elapsed = 3600 - remaining
        return int(elapsed // 900 + 1), int(900 - (elapsed % 900))

    @staticmethod
    def _seconds_to_period_boundary(remaining: int) -> int:
        if remaining <= 0:
            return 0
        modulo = remaining % 900
        return 900 if modulo == 0 else modulo

    def _duration(self, profile: TeamDriveProfile, remaining: int, *, low: int = 18, high: int = 46) -> int:
        return min(
            remaining,
            self._seconds_to_period_boundary(remaining),
            self._a_kernel._duration(profile, low=low, high=high),
        )
    def _short_duration(self, remaining: int, low: int, high: int) -> int:
        return min(
            remaining,
            self._seconds_to_period_boundary(remaining),
            int(self.rng.integers(low, high + 1)),
        )

    def _resolved_score(self, team: str, home_score: int, away_score: int) -> int:
        return home_score if team == self.home_team else away_score

    def _add_points(self, team: str, points: int, home_score: int, away_score: int) -> tuple[int, int]:
        if team == self.home_team:
            return home_score + points, away_score
        if team == self.away_team:
            return home_score, away_score + points
        raise ValueError("SCORING_TEAM_NOT_IN_GAME")

    def _resolve_td_try(self, team: str, play: PlayEvent) -> SpecialTeamsEvent:
        profile = self._special_profile(team)
        if self._c_kernel.rng.random() < profile.two_point_attempt_rate:
            made = bool(self._c_kernel.rng.random() < profile.two_point_success_rate)
            return SpecialTeamsEvent(
                source_play_id=play.play_id,
                period=play.quarter,
                clock_seconds_remaining=play.clock_seconds_remaining,
                team=team,
                event_type="TWO_POINT_MADE" if made else "TWO_POINT_MISSED",
                points=2 if made else 0,
            )
        self._c_kernel._require_kicker(profile)
        made = bool(self._c_kernel.rng.random() < self._c_kernel._xp_probability(profile))
        return SpecialTeamsEvent(
            source_play_id=play.play_id,
            period=play.quarter,
            clock_seconds_remaining=play.clock_seconds_remaining,
            team=team,
            event_type="XP_MADE" if made else "XP_MISSED",
            points=1 if made else 0,
            kicker_id=profile.kicker_id,
        )

    def _resolve_transition_td_try(self, team: str, transition: NFLPossessionTransition) -> SpecialTeamsEvent:
        profile = self._special_profile(team)
        if self._c_kernel.rng.random() < profile.two_point_attempt_rate:
            made = bool(self._c_kernel.rng.random() < profile.two_point_success_rate)
            return SpecialTeamsEvent(
                source_play_id=None,
                source_transition_index=transition.transition_index,
                period=transition.period,
                clock_seconds_remaining=transition.clock_seconds_remaining,
                team=team,
                event_type="TWO_POINT_MADE" if made else "TWO_POINT_MISSED",
                points=2 if made else 0,
            )
        self._c_kernel._require_kicker(profile)
        made = bool(self._c_kernel.rng.random() < self._c_kernel._xp_probability(profile))
        return SpecialTeamsEvent(
            source_play_id=None,
            source_transition_index=transition.transition_index,
            period=transition.period,
            clock_seconds_remaining=transition.clock_seconds_remaining,
            team=team,
            event_type="XP_MADE" if made else "XP_MISSED",
            points=1 if made else 0,
            kicker_id=profile.kicker_id,
        )

    def _resolve_field_goal(self, team: str, play: PlayEvent) -> SpecialTeamsEvent:
        profile = self._special_profile(team)
        self._c_kernel._require_kicker(profile)
        assert play.kick_distance is not None
        made = bool(self._c_kernel.rng.random() < self._c_kernel._fg_probability(profile, play.kick_distance))
        return SpecialTeamsEvent(
            source_play_id=play.play_id,
            period=play.quarter,
            clock_seconds_remaining=play.clock_seconds_remaining,
            team=team,
            event_type="FG_MADE" if made else "FG_MISSED",
            points=3 if made else 0,
            kicker_id=profile.kicker_id,
            kick_distance=play.kick_distance,
        )

    def _kickoff_chain(
        self,
        *,
        transition_index: int,
        source_play_id: int | None,
        next_drive_id: int,
        kicking_team: str,
        receiving_team: str,
        period: int,
        clock_seconds_remaining: int,
        kicking_team_trailing: bool,
        label: str,
        allow_onside: bool,
        transitions: list[NFLPossessionTransition],
        c_events: list[SpecialTeamsEvent],
        resolved_home: int,
        resolved_away: int,
    ) -> tuple[NFLPossessionTransition, int, int, int]:
        current_kicking = kicking_team
        current_receiving = receiving_team
        current_source = source_play_id
        current_label = label
        current_allow_onside = allow_onside
        trailing = bool(kicking_team_trailing)

        for _ in range(12):
            transition_index += 1
            transition = self._field.kickoff(
                transition_index=transition_index,
                source_play_id=current_source,
                next_drive_id=next_drive_id,
                kicking_team=current_kicking,
                receiving_team=current_receiving,
                period=period,
                clock_seconds_remaining=clock_seconds_remaining,
                kicking_team_trailing=trailing,
                label=current_label,
                allow_onside=current_allow_onside,
            )
            if transition.transition_type.endswith("_RETURN") and self._returns.is_touchdown(current_receiving, "KICKOFF"):
                transition = replace(
                    transition,
                    transition_type=f"{transition.transition_type}_TD",
                    creates_next_drive=False,
                )
                transitions.append(transition)
                c_events.append(
                    SpecialTeamsEvent(
                        source_play_id=None,
                        source_transition_index=transition.transition_index,
                        period=period,
                        clock_seconds_remaining=clock_seconds_remaining,
                        team=current_receiving,
                        event_type="KICKOFF_RETURN_TD",
                        points=6,
                    )
                )
                resolved_home, resolved_away = self._add_points(
                    current_receiving, 6, resolved_home, resolved_away
                )
                try_event = self._resolve_transition_td_try(current_receiving, transition)
                c_events.append(try_event)
                resolved_home, resolved_away = self._add_points(
                    current_receiving, try_event.points, resolved_home, resolved_away
                )

                prior_kicking = current_kicking
                current_kicking = current_receiving
                current_receiving = prior_kicking
                current_source = None
                current_label = "KICKOFF"
                current_allow_onside = True
                trailing = self._resolved_score(current_kicking, resolved_home, resolved_away) < self._resolved_score(
                    current_receiving, resolved_home, resolved_away
                )
                continue

            transitions.append(transition)
            return transition, transition_index, resolved_home, resolved_away

        raise ValueError("KICKOFF_RETURN_SCORE_CHAIN_LIMIT_EXCEEDED")

    def _punt_transition(
        self,
        *,
        transition_index: int,
        play: PlayEvent,
        next_drive_id: int,
        punting_team: str,
        receiving_team: str,
        period: int,
        clock_seconds_remaining: int,
        kicking_yardline_100: int,
        transitions: list[NFLPossessionTransition],
        c_events: list[SpecialTeamsEvent],
        resolved_home: int,
        resolved_away: int,
    ) -> tuple[NFLPossessionTransition, int, int, int]:
        transition_index += 1
        transition = self._field.punt(
            transition_index=transition_index,
            source_play_id=play.play_id,
            next_drive_id=next_drive_id,
            punting_team=punting_team,
            receiving_team=receiving_team,
            period=period,
            clock_seconds_remaining=clock_seconds_remaining,
            kicking_yardline_100=kicking_yardline_100,
        )
        if transition.transition_type == "PUNT_RETURN" and self._returns.is_touchdown(receiving_team, "PUNT"):
            transition = replace(
                transition,
                transition_type="PUNT_RETURN_TD",
                creates_next_drive=False,
            )
            transitions.append(transition)
            c_events.append(
                SpecialTeamsEvent(
                    source_play_id=None,
                    source_transition_index=transition.transition_index,
                    period=period,
                    clock_seconds_remaining=clock_seconds_remaining,
                    team=receiving_team,
                    event_type="PUNT_RETURN_TD",
                    points=6,
                )
            )
            resolved_home, resolved_away = self._add_points(
                receiving_team, 6, resolved_home, resolved_away
            )
            try_event = self._resolve_transition_td_try(receiving_team, transition)
            c_events.append(try_event)
            resolved_home, resolved_away = self._add_points(
                receiving_team, try_event.points, resolved_home, resolved_away
            )
            trailing = self._resolved_score(receiving_team, resolved_home, resolved_away) < self._resolved_score(
                punting_team, resolved_home, resolved_away
            )
            return self._kickoff_chain(
                transition_index=transition_index,
                source_play_id=None,
                next_drive_id=next_drive_id,
                kicking_team=receiving_team,
                receiving_team=punting_team,
                period=period,
                clock_seconds_remaining=clock_seconds_remaining,
                kicking_team_trailing=trailing,
                label="KICKOFF",
                allow_onside=True,
                transitions=transitions,
                c_events=c_events,
                resolved_home=resolved_home,
                resolved_away=resolved_away,
            )
        transitions.append(transition)
        return transition, transition_index, resolved_home, resolved_away

    def simulate(self) -> NFLIntegratedRegulationSimulation:
        remaining = 3600
        raw_home = raw_away = 0
        resolved_home = resolved_away = 0
        play_id = 0
        next_drive_id = 1
        transition_index = 0
        plays: list[PlayEvent] = []
        c_events: list[SpecialTeamsEvent] = []
        transitions: list[NFLPossessionTransition] = []

        opening_receiver = self.home_team if self.rng.random() < 0.5 else self.away_team
        opening_kicker = self._other(opening_receiver)
        second_half_receiver = opening_kicker

        pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
            transition_index=transition_index,
            source_play_id=None,
            next_drive_id=next_drive_id,
            kicking_team=opening_kicker,
            receiving_team=opening_receiver,
            period=1,
            clock_seconds_remaining=900,
            kicking_team_trailing=False,
            label="OPENING_KICKOFF",
            allow_onside=False,
            transitions=transitions,
            c_events=c_events,
            resolved_home=resolved_home,
            resolved_away=resolved_away,
        )
        halftime_kicked = False

        while remaining > 0 and next_drive_id <= 80:
            if remaining == 1800 and not halftime_kicked:
                halftime_kicked = True
                halftime_kicker = self._other(second_half_receiver)
                pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
                    transition_index=transition_index,
                    source_play_id=None,
                    next_drive_id=next_drive_id,
                    kicking_team=halftime_kicker,
                    receiving_team=second_half_receiver,
                    period=3,
                    clock_seconds_remaining=900,
                    kicking_team_trailing=False,
                    label="HALFTIME_KICKOFF",
                    allow_onside=False,
                    transitions=transitions,
                    c_events=c_events,
                    resolved_home=resolved_home,
                    resolved_away=resolved_away,
                )

            if pending is None:
                raise ValueError("INTEGRATED_NEXT_POSSESSION_TRANSITION_REQUIRED")
            if not pending.creates_next_drive:
                raise ValueError("INTEGRATED_PENDING_TRANSITION_MUST_CREATE_DRIVE")

            drive_id = next_drive_id
            next_drive_id += 1
            possession = pending.next_possession_team
            yardline = pending.next_yardline_100
            profile = self._drive_profile(possession)
            down = 1
            distance = max(1, min(10, yardline))
            pending = None
            drive_ended = False

            for _ in range(30):
                if remaining <= 0 or (remaining == 1800 and not halftime_kicked):
                    break

                opponent = self._other(possession)
                next_id = next_drive_id

                if down == 4 and yardline <= 35 and self.rng.random() < profile.field_goal_attempt_rate:
                    duration = self._short_duration(remaining, 4, 8)
                    remaining -= duration
                    quarter, clock = self._play_end_period_clock(remaining)
                    kick_distance = int(yardline + 17)
                    play_id += 1
                    play = PlayEvent(
                        drive_id=drive_id,
                        play_id=play_id,
                        quarter=quarter,
                        clock_seconds_remaining=clock,
                        possession=possession,
                        score_before_home=raw_home,
                        score_before_away=raw_away,
                        score_after_home=raw_home,
                        score_after_away=raw_away,
                        down=down,
                        distance=distance,
                        yardline_100=yardline,
                        play_type="FIELD_GOAL",
                        yards=0,
                        points=0,
                        score_type="FIELD_GOAL_ATTEMPT_CANDIDATE",
                        kick_distance=kick_distance,
                    )
                    plays.append(play)
                    event = self._resolve_field_goal(possession, play)
                    c_events.append(event)
                    resolved_home, resolved_away = self._add_points(
                        possession, event.points, resolved_home, resolved_away
                    )
                    if remaining not in (0, 1800):
                        period, transition_clock = self._transition_period_clock(remaining)
                        if event.event_type == "FG_MADE":
                            trailing = self._resolved_score(possession, resolved_home, resolved_away) < self._resolved_score(
                                opponent, resolved_home, resolved_away
                            )
                            pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
                                transition_index=transition_index,
                                source_play_id=play.play_id,
                                next_drive_id=next_id,
                                kicking_team=possession,
                                receiving_team=opponent,
                                period=period,
                                clock_seconds_remaining=transition_clock,
                                kicking_team_trailing=trailing,
                                label="KICKOFF",
                                allow_onside=True,
                                transitions=transitions,
                                c_events=c_events,
                                resolved_home=resolved_home,
                                resolved_away=resolved_away,
                            )
                        else:
                            transition_index += 1
                            pending = self._field.missed_field_goal(
                                transition_index=transition_index,
                                source_play_id=play.play_id,
                                next_drive_id=next_id,
                                kicking_team=possession,
                                receiving_team=opponent,
                                period=period,
                                clock_seconds_remaining=transition_clock,
                                line_of_scrimmage_yardline_100=yardline,
                            )
                            transitions.append(pending)
                    drive_ended = True
                    break

                if down == 4 and yardline > 60:
                    duration = self._short_duration(remaining, 6, 10)
                    remaining -= duration
                    quarter, clock = self._play_end_period_clock(remaining)
                    play_id += 1
                    play = PlayEvent(
                        drive_id=drive_id,
                        play_id=play_id,
                        quarter=quarter,
                        clock_seconds_remaining=clock,
                        possession=possession,
                        score_before_home=raw_home,
                        score_before_away=raw_away,
                        score_after_home=raw_home,
                        score_after_away=raw_away,
                        down=down,
                        distance=distance,
                        yardline_100=yardline,
                        play_type="PUNT",
                        yards=0,
                        points=0,
                    )
                    plays.append(play)
                    if remaining not in (0, 1800):
                        period, transition_clock = self._transition_period_clock(remaining)
                        pending, transition_index, resolved_home, resolved_away = self._punt_transition(
                            transition_index=transition_index,
                            play=play,
                            next_drive_id=next_id,
                            punting_team=possession,
                            receiving_team=opponent,
                            period=period,
                            clock_seconds_remaining=transition_clock,
                            kicking_yardline_100=yardline,
                            transitions=transitions,
                            c_events=c_events,
                            resolved_home=resolved_home,
                            resolved_away=resolved_away,
                        )
                    drive_ended = True
                    break

                before_home, before_away = raw_home, raw_away
                duration = self._duration(profile, remaining)
                remaining -= duration
                quarter, clock = self._play_end_period_clock(remaining)
                play_type = "PASS" if self.rng.random() < profile.pass_rate else "RUSH"

                if play_type == "PASS" and self.rng.random() < profile.sack_rate:
                    play_type = "SACK"
                    pass_complete = None
                    yards = self._a_kernel._sack_yards()
                else:
                    if self.rng.random() < profile.turnover_rate:
                        turnover_type = "INTERCEPTION" if play_type == "PASS" else "FUMBLE"
                        pass_complete = False if play_type == "PASS" else None
                        yards = 0 if play_type == "PASS" else self._a_kernel._regular_play_yards(profile, play_type)
                        after_yardline = max(0, min(100, yardline - yards))
                        return_td = self._returns.is_touchdown(opponent, "TURNOVER")
                        points = 6 if return_td else 0
                        score_type = "DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE" if return_td else None
                        if return_td:
                            raw_home, raw_away = self._add_points(opponent, 6, raw_home, raw_away)
                            resolved_home, resolved_away = self._add_points(opponent, 6, resolved_home, resolved_away)

                        play_id += 1
                        play = PlayEvent(
                            drive_id=drive_id,
                            play_id=play_id,
                            quarter=quarter,
                            clock_seconds_remaining=clock,
                            possession=possession,
                            score_before_home=before_home,
                            score_before_away=before_away,
                            score_after_home=raw_home,
                            score_after_away=raw_away,
                            down=down,
                            distance=distance,
                            yardline_100=yardline,
                            play_type=play_type,
                            yards=yards,
                            points=points,
                            score_type=score_type,
                            turnover_type=turnover_type,
                            pass_complete=pass_complete,
                        )
                        plays.append(play)

                        if return_td:
                            try_event = self._resolve_td_try(opponent, play)
                            c_events.append(try_event)
                            resolved_home, resolved_away = self._add_points(
                                opponent, try_event.points, resolved_home, resolved_away
                            )
                            if remaining not in (0, 1800):
                                period, transition_clock = self._transition_period_clock(remaining)
                                trailing = self._resolved_score(opponent, resolved_home, resolved_away) < self._resolved_score(
                                    possession, resolved_home, resolved_away
                                )
                                pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
                                    transition_index=transition_index,
                                    source_play_id=play.play_id,
                                    next_drive_id=next_id,
                                    kicking_team=opponent,
                                    receiving_team=possession,
                                    period=period,
                                    clock_seconds_remaining=transition_clock,
                                    kicking_team_trailing=trailing,
                                    label="KICKOFF",
                                    allow_onside=True,
                                    transitions=transitions,
                                    c_events=c_events,
                                    resolved_home=resolved_home,
                                    resolved_away=resolved_away,
                                )
                        elif remaining not in (0, 1800):
                            transition_index += 1
                            period, transition_clock = self._transition_period_clock(remaining)
                            pending = self._field.turnover(
                                transition_index=transition_index,
                                source_play_id=play.play_id,
                                next_drive_id=next_id,
                                offense_team=possession,
                                defense_team=opponent,
                                period=period,
                                clock_seconds_remaining=transition_clock,
                                offense_yardline_100_after_play=after_yardline,
                                transition_type=turnover_type,
                            )
                            transitions.append(pending)
                        drive_ended = True
                        break

                    if play_type == "PASS":
                        pass_complete = bool(self.rng.random() < profile.completion_rate)
                        yards = self._a_kernel._regular_play_yards(profile, play_type) if pass_complete else 0
                    else:
                        pass_complete = None
                        yards = self._a_kernel._regular_play_yards(profile, play_type)

                raw_new_yardline = yardline - yards
                safety = raw_new_yardline >= 100 and yards < 0
                touchdown = raw_new_yardline <= 0 and (play_type != "PASS" or pass_complete)
                points = 0
                score_type = None

                if safety:
                    points = 2
                    score_type = "SAFETY_CANDIDATE"
                    raw_home, raw_away = self._add_points(opponent, 2, raw_home, raw_away)
                    resolved_home, resolved_away = self._add_points(opponent, 2, resolved_home, resolved_away)
                elif touchdown:
                    points = 6
                    score_type = "TOUCHDOWN_CANDIDATE"
                    raw_home, raw_away = self._add_points(possession, 6, raw_home, raw_away)
                    resolved_home, resolved_away = self._add_points(possession, 6, resolved_home, resolved_away)

                play_id += 1
                play = PlayEvent(
                    drive_id=drive_id,
                    play_id=play_id,
                    quarter=quarter,
                    clock_seconds_remaining=clock,
                    possession=possession,
                    score_before_home=before_home,
                    score_before_away=before_away,
                    score_after_home=raw_home,
                    score_after_away=raw_away,
                    down=down,
                    distance=distance,
                    yardline_100=yardline,
                    play_type=play_type,
                    yards=yards,
                    points=points,
                    score_type=score_type,
                    pass_complete=pass_complete,
                )
                plays.append(play)

                if safety:
                    if remaining not in (0, 1800):
                        period, transition_clock = self._transition_period_clock(remaining)
                        trailing = self._resolved_score(possession, resolved_home, resolved_away) < self._resolved_score(
                            opponent, resolved_home, resolved_away
                        )
                        pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
                            transition_index=transition_index,
                            source_play_id=play.play_id,
                            next_drive_id=next_id,
                            kicking_team=possession,
                            receiving_team=opponent,
                            period=period,
                            clock_seconds_remaining=transition_clock,
                            kicking_team_trailing=trailing,
                            label="SAFETY_KICK",
                            allow_onside=False,
                            transitions=transitions,
                            c_events=c_events,
                            resolved_home=resolved_home,
                            resolved_away=resolved_away,
                        )
                    drive_ended = True
                    break

                if touchdown:
                    try_event = self._resolve_td_try(possession, play)
                    c_events.append(try_event)
                    resolved_home, resolved_away = self._add_points(
                        possession, try_event.points, resolved_home, resolved_away
                    )
                    if remaining not in (0, 1800):
                        period, transition_clock = self._transition_period_clock(remaining)
                        trailing = self._resolved_score(possession, resolved_home, resolved_away) < self._resolved_score(
                            opponent, resolved_home, resolved_away
                        )
                        pending, transition_index, resolved_home, resolved_away = self._kickoff_chain(
                            transition_index=transition_index,
                            source_play_id=play.play_id,
                            next_drive_id=next_id,
                            kicking_team=possession,
                            receiving_team=opponent,
                            period=period,
                            clock_seconds_remaining=transition_clock,
                            kicking_team_trailing=trailing,
                            label="KICKOFF",
                            allow_onside=True,
                            transitions=transitions,
                            c_events=c_events,
                            resolved_home=resolved_home,
                            resolved_away=resolved_away,
                        )
                    drive_ended = True
                    break

                new_yardline = max(1, min(99, raw_new_yardline))
                converted = (pass_complete is True and yards >= distance) if play_type == "PASS" else yards >= distance
                yardline = new_yardline

                if remaining == 1800 and not halftime_kicked:
                    drive_ended = True
                    break
                if converted:
                    down = 1
                    distance = max(1, min(10, yardline))
                    continue
                if down == 4:
                    if remaining not in (0, 1800):
                        transition_index += 1
                        period, transition_clock = self._transition_period_clock(remaining)
                        pending = self._field.turnover(
                            transition_index=transition_index,
                            source_play_id=play.play_id,
                            next_drive_id=next_id,
                            offense_team=possession,
                            defense_team=opponent,
                            period=period,
                            clock_seconds_remaining=transition_clock,
                            offense_yardline_100_after_play=yardline,
                            transition_type="TURNOVER_ON_DOWNS",
                        )
                        transitions.append(pending)
                    drive_ended = True
                    break
                distance = max(1, distance - yards)
                down += 1

            if remaining == 1800 and not halftime_kicked:
                pending = None
                continue
            if remaining <= 0:
                break
            if not drive_ended:
                raise ValueError("INTEGRATED_DRIVE_PLAY_LIMIT_EXCEEDED")
            if pending is None:
                raise ValueError("INTEGRATED_DRIVE_END_TRANSITION_MISSING")

        if remaining > 0:
            raise ValueError("INTEGRATED_REGULATION_DRIVE_LIMIT_EXCEEDED")

        raw_path = FootballPlayPath(
            game_id=self.game_id,
            simulation_id=0,
            home_team=self.home_team,
            away_team=self.away_team,
            plays=tuple(plays),
        )
        raw_path.assert_reconciliation()
        resolved_path = ResolvedFootballPath(
            raw_path,
            tuple(c_events),
            self.home_special_teams,
            self.away_special_teams,
        )
        resolved_path.assert_reconciliation()
        result = NFLIntegratedRegulationSimulation(
            raw_path=raw_path,
            resolved_path=resolved_path,
            transitions=tuple(transitions),
            final_home_score=resolved_home,
            final_away_score=resolved_away,
            opening_receiving_team=opening_receiver,
            second_half_receiving_team=second_half_receiver,
        )
        result.assert_reconciliation()
        return result