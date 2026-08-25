"""Structural drive/play Engine A challenger for football.

Engine A owns regulation possession, down/distance, field position, play type,
yards, turnovers and raw offensive touchdown outcomes. Special-teams outcomes
are deliberately unresolved here: field-goal attempts carry zero points until
Engine C resolves them, and touchdowns contribute six raw points before Engine
C resolves the post-TD try.

The default parameters are transparent structural candidate defaults, not fitted
NFL promotion parameters. No sportsbook line, price or implied probability is
accepted anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .football_path import FootballGamePath, ScoringEvent


@dataclass(frozen=True)
class TeamDriveProfile:
    """Market-blind candidate parameters for one offense's drive process."""

    pass_rate: float = 0.56
    completion_rate: float = 0.64
    success_rate: float = 0.45
    explosive_rate: float = 0.10
    turnover_rate: float = 0.018
    # Matchup-level probability that a called pass becomes a sack before a pass
    # attempt is recorded. This is a structural candidate input until fitted.
    sack_rate: float = 0.065
    field_goal_attempt_rate: float = 0.82
    # Deprecated structural field retained for source compatibility only.
    # Engine A does not consume this value; Engine C owns kick resolution.
    field_goal_skill: float = 0.84
    pace_seconds_mean: float = 31.0

    def __post_init__(self) -> None:
        for name in (
            "pass_rate",
            "completion_rate",
            "success_rate",
            "explosive_rate",
            "turnover_rate",
            "sack_rate",
            "field_goal_attempt_rate",
            "field_goal_skill",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"TEAM_DRIVE_PROFILE_RATE_OUT_OF_RANGE:{name}")
        if self.pace_seconds_mean <= 0:
            raise ValueError("TEAM_DRIVE_PROFILE_PACE_MUST_BE_POSITIVE")


@dataclass(frozen=True)
class PlayEvent:
    """One ordered regulation play with raw Engine A score state."""

    drive_id: int
    play_id: int
    quarter: int
    clock_seconds_remaining: int
    possession: str
    score_before_home: int
    score_before_away: int
    score_after_home: int
    score_after_away: int
    down: int
    distance: int
    yardline_100: int
    play_type: str
    yards: int
    points: int = 0
    score_type: str | None = None
    turnover_type: str | None = None
    pass_complete: bool | None = None
    penalty_no_play: bool = False
    personnel_package: str = "UNKNOWN"
    kick_distance: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.drive_id, bool) or not isinstance(self.drive_id, int) or self.drive_id <= 0:
            raise ValueError("DRIVE_ID_INVALID")
        if isinstance(self.play_id, bool) or not isinstance(self.play_id, int) or self.play_id <= 0:
            raise ValueError("PLAY_ID_INVALID")
        if self.quarter not in (1, 2, 3, 4):
            raise ValueError("PLAY_QUARTER_INVALID")
        if not 0 <= self.clock_seconds_remaining <= 900:
            raise ValueError("PLAY_CLOCK_INVALID")
        if not str(self.possession).strip():
            raise ValueError("PLAY_POSSESSION_REQUIRED")
        if self.down not in (1, 2, 3, 4):
            raise ValueError("PLAY_DOWN_INVALID")
        if isinstance(self.distance, bool) or not isinstance(self.distance, int) or self.distance <= 0:
            raise ValueError("PLAY_DISTANCE_INVALID")
        if isinstance(self.yardline_100, bool) or not isinstance(self.yardline_100, int) or not 0 <= self.yardline_100 <= 100:
            raise ValueError("PLAY_YARDLINE_INVALID")
        if not str(self.play_type).strip():
            raise ValueError("PLAY_TYPE_REQUIRED")
        if isinstance(self.points, bool) or not isinstance(self.points, int) or self.points < 0:
            raise ValueError("PLAY_POINTS_INVALID")
        scores = (
            self.score_before_home,
            self.score_before_away,
            self.score_after_home,
            self.score_after_away,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in scores):
            raise ValueError("PLAY_SCORE_STATE_INVALID")

        home_delta = self.score_after_home - self.score_before_home
        away_delta = self.score_after_away - self.score_before_away
        if home_delta < 0 or away_delta < 0 or home_delta + away_delta != self.points:
            raise ValueError("PLAY_SCORING_DELTA_INVALID")
        if home_delta > 0 and away_delta > 0:
            raise ValueError("PLAY_MULTIPLE_SCORING_TEAMS_INVALID")
        if self.points > 0 and not self.score_type:
            raise ValueError("PLAY_SCORE_TYPE_REQUIRED")

        play_type = str(self.play_type).upper()
        if self.score_type == "TOUCHDOWN_CANDIDATE" and self.points != 6:
            raise ValueError("ENGINE_A_TOUCHDOWN_MUST_BE_SIX_RAW_POINTS")
        if self.score_type == "DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE":
            if self.points != 6:
                raise ValueError("ENGINE_A_DEFENSIVE_RETURN_TD_MUST_BE_SIX_RAW_POINTS")
            if self.turnover_type not in {"INTERCEPTION", "FUMBLE"}:
                raise ValueError("DEFENSIVE_RETURN_TD_REQUIRES_TURNOVER")
            if play_type == "PASS" and self.turnover_type != "INTERCEPTION":
                raise ValueError("PASS_DEFENSIVE_RETURN_TD_REQUIRES_INTERCEPTION")
            if play_type == "RUSH" and self.turnover_type != "FUMBLE":
                raise ValueError("RUSH_DEFENSIVE_RETURN_TD_REQUIRES_FUMBLE")
        if self.score_type == "SAFETY_CANDIDATE" and self.points != 2:
            raise ValueError("ENGINE_A_SAFETY_MUST_BE_TWO_RAW_POINTS")
        if play_type == "FIELD_GOAL":
            if self.points != 0 or home_delta != 0 or away_delta != 0:
                raise ValueError("ENGINE_A_FIELD_GOAL_MUST_BE_UNRESOLVED")
            if self.score_type != "FIELD_GOAL_ATTEMPT_CANDIDATE":
                raise ValueError("ENGINE_A_FIELD_GOAL_ATTEMPT_TAG_REQUIRED")
            if self.kick_distance is None:
                raise ValueError("FIELD_GOAL_DISTANCE_REQUIRED")
        if play_type == "SACK":
            if self.yards >= 0:
                raise ValueError("SACK_YARDS_MUST_BE_NEGATIVE")
            if self.turnover_type == "INTERCEPTION":
                raise ValueError("SACK_CANNOT_BE_INTERCEPTION")

        if play_type == "PASS":
            if not isinstance(self.pass_complete, bool):
                raise ValueError("PASS_COMPLETION_STATE_REQUIRED")
            if self.turnover_type == "INTERCEPTION" and self.pass_complete:
                raise ValueError("INTERCEPTION_CANNOT_BE_COMPLETE")
            defensive_pick_six = (
                self.score_type == "DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE"
                and self.turnover_type == "INTERCEPTION"
                and self.points == 6
            )
            if not self.pass_complete and (
                self.yards != 0 or (self.points != 0 and not defensive_pick_six)
            ):
                raise ValueError("INCOMPLETE_PASS_STATE_INVALID")
        elif self.pass_complete is not None:
            raise ValueError("NON_PASS_COMPLETION_STATE_INVALID")

        if self.penalty_no_play and (
            self.points != 0
            or home_delta != 0
            or away_delta != 0
            or self.yards != 0
            or self.turnover_type is not None
        ):
            raise ValueError("NO_PLAY_CANNOT_CHANGE_STATE")
        if self.kick_distance is not None:
            if isinstance(self.kick_distance, bool) or not isinstance(self.kick_distance, int) or self.kick_distance <= 0:
                raise ValueError("KICK_DISTANCE_INVALID")


@dataclass(frozen=True)
class FootballPlayPath:
    """One immutable regulation Engine A play path for a simulated game."""

    game_id: str
    simulation_id: int
    home_team: str
    away_team: str
    plays: tuple[PlayEvent, ...]

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("GAME_ID_REQUIRED")
        if not self.home_team or not self.away_team or self.home_team == self.away_team:
            raise ValueError("INVALID_TEAM_IDENTITY")
        if any(play.possession not in {self.home_team, self.away_team} for play in self.plays):
            raise ValueError("PLAY_POSSESSION_TEAM_MISMATCH")

        ids = [play.play_id for play in self.plays]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_PLAY_ID")
        if ids and ids != list(range(1, len(ids) + 1)):
            raise ValueError("PLAY_IDS_NOT_CONTIGUOUS")
        drives = [play.drive_id for play in self.plays]
        if drives != sorted(drives):
            raise ValueError("DRIVE_ORDER_INVALID")

        previous: PlayEvent | None = None
        previous_elapsed = -1
        drive_possession: dict[int, str] = {}
        for play in self.plays:
            elapsed = (play.quarter - 1) * 900 + (900 - play.clock_seconds_remaining)
            if elapsed < previous_elapsed:
                raise ValueError("PLAY_CLOCK_ORDER_INVALID")
            previous_elapsed = elapsed

            existing = drive_possession.setdefault(play.drive_id, play.possession)
            if existing != play.possession:
                raise ValueError("DRIVE_POSSESSION_CHANGED")

            if previous is None:
                if play.score_before_home != 0 or play.score_before_away != 0:
                    raise ValueError("PLAY_PATH_INITIAL_SCORE_NONZERO")
            else:
                if (
                    play.score_before_home != previous.score_after_home
                    or play.score_before_away != previous.score_after_away
                ):
                    raise ValueError("PLAY_SCORE_CHAIN_BROKEN")

            if play.points > 0:
                home_delta = play.score_after_home - play.score_before_home
                away_delta = play.score_after_away - play.score_before_away
                if home_delta == play.points and away_delta == 0:
                    scoring_team = self.home_team
                elif away_delta == play.points and home_delta == 0:
                    scoring_team = self.away_team
                else:
                    raise ValueError("PLAY_SCORING_TEAM_UNRESOLVED")
                if play.score_type == "TOUCHDOWN_CANDIDATE" and scoring_team != play.possession:
                    raise ValueError("OFFENSIVE_TD_SCORING_TEAM_MISMATCH")
                if play.score_type == "DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE" and scoring_team == play.possession:
                    raise ValueError("DEFENSIVE_RETURN_TD_SCORING_TEAM_MISMATCH")
                if play.score_type == "SAFETY_CANDIDATE" and scoring_team == play.possession:
                    raise ValueError("SAFETY_SCORING_TEAM_MISMATCH")
            previous = play

    def to_scoring_path(self) -> FootballGamePath:
        """Collapse raw Engine A scoring plays into the canonical score path.

        The result intentionally excludes field goals, XPs and two-point tries;
        Engine C owns those outcomes. A touchdown therefore appears as six raw
        points here.
        """

        events: list[ScoringEvent] = []
        for play in self.plays:
            if play.points <= 0:
                continue
            home_delta = play.score_after_home - play.score_before_home
            away_delta = play.score_after_away - play.score_before_away
            if home_delta == play.points and away_delta == 0:
                team = self.home_team
            elif away_delta == play.points and home_delta == 0:
                team = self.away_team
            else:
                raise ValueError("PLAY_SCORING_TEAM_UNRESOLVED")
            events.append(
                ScoringEvent(
                    event_id=f"{self.simulation_id}:play:{play.play_id:05d}",
                    period=play.quarter,
                    clock_seconds_remaining=play.clock_seconds_remaining,
                    team=team,
                    points=play.points,
                    score_type=str(play.score_type),
                )
            )
        scoring_path = FootballGamePath(
            game_id=self.game_id,
            simulation_id=self.simulation_id,
            home_team=self.home_team,
            away_team=self.away_team,
            events=tuple(events),
        )
        scoring_path.assert_conservation()
        return scoring_path

    def assert_reconciliation(self) -> None:
        scoring_path = self.to_scoring_path()
        row = scoring_path.to_market_row()
        final_home = self.plays[-1].score_after_home if self.plays else 0
        final_away = self.plays[-1].score_after_away if self.plays else 0
        if row["home_score"] != final_home:
            raise ValueError("PLAY_PATH_HOME_SCORE_RECONCILIATION_FAILED")
        if row["away_score"] != final_away:
            raise ValueError("PLAY_PATH_AWAY_SCORE_RECONCILIATION_FAILED")


class EngineADrivePlaySimulator:
    """Seeded regulation drive/play state-machine challenger.

    Engine A does not resolve field goals or post-TD tries. It deliberately does
    not implement NFL overtime, defensive-return scoring, full penalties,
    detailed punt/return state, or fitted special-teams behavior yet. Those
    omissions remain promotion blockers rather than hidden approximations.
    """

    def __init__(
        self,
        *,
        game_id: str,
        home_team: str,
        away_team: str,
        home_profile: TeamDriveProfile,
        away_profile: TeamDriveProfile,
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

        self.game_id = game_id
        self.home_team = home_team
        self.away_team = away_team
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    @staticmethod
    def _period_clock(game_seconds_remaining: int) -> tuple[int, int]:
        remaining = max(0, min(3600, int(game_seconds_remaining)))
        if remaining == 0:
            return 4, 0
        elapsed = 3600 - remaining
        quarter = min(4, elapsed // 900 + 1)
        clock = 900 - (elapsed % 900)
        return int(quarter), int(clock)

    def _duration(self, profile: TeamDriveProfile, *, low: int = 18, high: int = 46) -> int:
        draw = int(round(self.rng.normal(profile.pace_seconds_mean, 5.0)))
        return max(low, min(high, draw))

    def _regular_play_yards(self, profile: TeamDriveProfile, play_type: str) -> int:
        success = bool(self.rng.random() < profile.success_rate)
        explosive = bool(self.rng.random() < profile.explosive_rate)
        if play_type == "PASS":
            mean = 7.5 if success else 3.0
            deviation = 5.5 if success else 3.5
        else:
            mean = 5.0 if success else 1.0
            deviation = 3.5 if success else 2.5
        yards = int(round(self.rng.normal(mean, deviation)))
        if success and explosive:
            yards += int(self.rng.integers(10, 26))
        return max(-12, min(45, yards))

    def _sack_yards(self) -> int:
        loss = int(round(abs(self.rng.normal(7.0, 3.0))))
        return -max(1, min(20, loss))

    def _simulate_one(self, simulation_id: int) -> FootballPlayPath:
        remaining = 3600
        home_score = 0
        away_score = 0
        play_id = 0
        drive_id = 0
        plays: list[PlayEvent] = []
        possession = self.home_team if self.rng.random() < 0.5 else self.away_team

        # Every drive consumes at least one positive-duration scrimmage play.
        # Regulation clock therefore provides the natural termination bound;
        # an arbitrary drive-count cap can silently return a partial game.
        while remaining > 0:
            drive_id += 1
            profile = self.home_profile if possession == self.home_team else self.away_profile
            yardline = 75
            down = 1
            distance = 10

            for _ in range(18):
                if remaining <= 0:
                    break

                if down == 4 and yardline <= 35 and self.rng.random() < profile.field_goal_attempt_rate:
                    duration = min(remaining, int(self.rng.integers(4, 9)))
                    remaining -= duration
                    quarter, clock = self._period_clock(remaining)
                    before_home, before_away = home_score, away_score
                    kick_distance = int(yardline + 17)
                    play_id += 1
                    plays.append(
                        PlayEvent(
                            drive_id=drive_id,
                            play_id=play_id,
                            quarter=quarter,
                            clock_seconds_remaining=clock,
                            possession=possession,
                            score_before_home=before_home,
                            score_before_away=before_away,
                            score_after_home=home_score,
                            score_after_away=away_score,
                            down=down,
                            distance=distance,
                            yardline_100=yardline,
                            play_type="FIELD_GOAL",
                            yards=0,
                            points=0,
                            score_type="FIELD_GOAL_ATTEMPT_CANDIDATE",
                            kick_distance=kick_distance,
                        )
                    )
                    break

                if down == 4 and yardline > 60:
                    duration = min(remaining, int(self.rng.integers(6, 11)))
                    remaining -= duration
                    quarter, clock = self._period_clock(remaining)
                    play_id += 1
                    plays.append(
                        PlayEvent(
                            drive_id=drive_id,
                            play_id=play_id,
                            quarter=quarter,
                            clock_seconds_remaining=clock,
                            possession=possession,
                            score_before_home=home_score,
                            score_before_away=away_score,
                            score_after_home=home_score,
                            score_after_away=away_score,
                            down=down,
                            distance=distance,
                            yardline_100=yardline,
                            play_type="PUNT",
                            yards=0,
                            points=0,
                        )
                    )
                    break

                before_home, before_away = home_score, away_score
                duration = min(remaining, self._duration(profile))
                remaining -= duration
                quarter, clock = self._period_clock(remaining)
                play_type = "PASS" if self.rng.random() < profile.pass_rate else "RUSH"

                if play_type == "PASS" and self.rng.random() < profile.sack_rate:
                    play_type = "SACK"
                    pass_complete = None
                    yards = self._sack_yards()
                else:
                    if self.rng.random() < profile.turnover_rate:
                        turnover_type = "INTERCEPTION" if play_type == "PASS" else "FUMBLE"
                        pass_complete = False if play_type == "PASS" else None
                        yards = 0 if play_type == "PASS" else self._regular_play_yards(profile, play_type)
                        play_id += 1
                        plays.append(
                            PlayEvent(
                                drive_id=drive_id,
                                play_id=play_id,
                                quarter=quarter,
                                clock_seconds_remaining=clock,
                                possession=possession,
                                score_before_home=before_home,
                                score_before_away=before_away,
                                score_after_home=home_score,
                                score_after_away=away_score,
                                down=down,
                                distance=distance,
                                yardline_100=yardline,
                                play_type=play_type,
                                yards=yards,
                                points=0,
                                turnover_type=turnover_type,
                                pass_complete=pass_complete,
                            )
                        )
                        break

                    if play_type == "PASS":
                        pass_complete = bool(self.rng.random() < profile.completion_rate)
                        yards = self._regular_play_yards(profile, play_type) if pass_complete else 0
                    else:
                        pass_complete = None
                        yards = self._regular_play_yards(profile, play_type)

                new_yardline = max(0, min(99, yardline - yards))
                touchdown = new_yardline == 0 and (play_type != "PASS" or pass_complete)
                points = 6 if touchdown else 0
                if touchdown and possession == self.home_team:
                    home_score += 6
                elif touchdown:
                    away_score += 6

                play_id += 1
                plays.append(
                    PlayEvent(
                        drive_id=drive_id,
                        play_id=play_id,
                        quarter=quarter,
                        clock_seconds_remaining=clock,
                        possession=possession,
                        score_before_home=before_home,
                        score_before_away=before_away,
                        score_after_home=home_score,
                        score_after_away=away_score,
                        down=down,
                        distance=distance,
                        yardline_100=yardline,
                        play_type=play_type,
                        yards=yards,
                        points=points,
                        score_type="TOUCHDOWN_CANDIDATE" if touchdown else None,
                        pass_complete=pass_complete,
                    )
                )

                if touchdown:
                    break
                converted = (pass_complete is True and yards >= distance) if play_type == "PASS" else yards >= distance
                yardline = max(1, min(99, new_yardline))
                if converted:
                    down = 1
                    distance = max(1, min(10, yardline))
                    continue
                if down == 4:
                    break
                distance = max(1, distance - yards)
                down += 1

            possession = self.away_team if possession == self.home_team else self.home_team

        path = FootballPlayPath(
            game_id=self.game_id,
            simulation_id=simulation_id,
            home_team=self.home_team,
            away_team=self.away_team,
            plays=tuple(plays),
        )
        path.assert_reconciliation()
        return path

    def simulate(self, n: int) -> list[FootballPlayPath]:
        if n <= 0:
            return []
        return [self._simulate_one(simulation_id) for simulation_id in range(int(n))]
