"""Deterministic football Engine-A play-path candidate.

This is a structural simulator, not a promoted predictive model.  It creates one
shared play path per simulation and derives quarter/half/final scores from the
same events.  Market prices must be read-outs from these paths; no half/quarter
market is allowed to draw an independent score.

The team profiles are expected to be produced from market-blind point-in-time
features.  Historical fitting/calibration and promotion remain separate gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

import numpy as np


_PROB_FIELDS = (
    "pass_rate",
    "completion_rate",
    "sack_rate",
    "interception_rate",
    "fumble_rate",
    "field_goal_make_prob",
)


@dataclass(frozen=True)
class TeamPlayProfile:
    pass_rate: float
    completion_rate: float
    sack_rate: float
    interception_rate: float
    fumble_rate: float
    run_yards_mean: float
    run_yards_sd: float
    completion_yards_mean: float
    completion_yards_sd: float
    pace_seconds_mean: float
    field_goal_make_prob: float

    def __post_init__(self) -> None:
        for name in _PROB_FIELDS:
            value = float(getattr(self, name))
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"PROFILE_PROBABILITY_OUT_OF_RANGE:{name}")
        for name in ("run_yards_sd", "completion_yards_sd", "pace_seconds_mean"):
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"PROFILE_POSITIVE_VALUE_REQUIRED:{name}")
        for name in ("run_yards_mean", "completion_yards_mean"):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"PROFILE_NONFINITE:{name}")


@dataclass(frozen=True)
class PlayEvent:
    game_id: str
    simulation_id: int
    drive_id: int
    play_id: int
    quarter: int
    seconds_remaining_before: int
    seconds_remaining_after: int
    possession: str
    score_before_home: int
    score_before_away: int
    score_after_home: int
    score_after_away: int
    down: int
    distance: int
    yardline: int
    play_type: str
    yards: int
    turnover_type: str | None
    scoring_team: str | None
    points: int
    drive_terminal: str | None


@dataclass(frozen=True)
class GamePath:
    game_id: str
    simulation_id: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    q1_home: int
    q1_away: int
    q2_home: int
    q2_away: int
    q3_home: int
    q3_away: int
    q4_home: int
    q4_away: int
    ot_home: int
    ot_away: int
    plays: tuple[PlayEvent, ...]

    @property
    def first_half_home_score(self) -> int:
        return self.q1_home + self.q2_home

    @property
    def first_half_away_score(self) -> int:
        return self.q1_away + self.q2_away

    @property
    def total(self) -> int:
        return self.home_score + self.away_score

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    def as_market_row(self) -> dict[str, int]:
        return {
            "home_score": self.home_score,
            "away_score": self.away_score,
            "first_half_home_score": self.first_half_home_score,
            "first_half_away_score": self.first_half_away_score,
            "q1_home_score": self.q1_home,
            "q1_away_score": self.q1_away,
            "q2_home_score": self.q2_home,
            "q2_away_score": self.q2_away,
            "q3_home_score": self.q3_home,
            "q3_away_score": self.q3_away,
            "q4_home_score": self.q4_home,
            "q4_away_score": self.q4_away,
            "ot_home_score": self.ot_home,
            "ot_away_score": self.ot_away,
            "total": self.total,
            "margin": self.margin,
        }


def _quarter(seconds_remaining: int) -> int:
    # Regulation clock represented as one 3600-second countdown.
    if seconds_remaining <= 0:
        return 4
    elapsed = 3600 - seconds_remaining
    return min(4, max(1, elapsed // 900 + 1))


def _bounded_yardline(value: int) -> int:
    return max(0, min(100, int(value)))


class FootballPathSimulator:
    def __init__(
        self,
        *,
        game_id: str,
        home_team: str,
        away_team: str,
        home_profile: TeamPlayProfile,
        away_profile: TeamPlayProfile,
        seed: int,
    ) -> None:
        if not str(game_id).strip():
            raise ValueError("GAME_ID_REQUIRED")
        if not str(home_team).strip() or not str(away_team).strip():
            raise ValueError("TEAM_ID_REQUIRED")
        if str(home_team) == str(away_team):
            raise ValueError("HOME_AWAY_TEAM_COLLISION")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("EXPLICIT_INTEGER_SEED_REQUIRED")
        self.game_id = str(game_id)
        self.home_team = str(home_team)
        self.away_team = str(away_team)
        self.home_profile = home_profile
        self.away_profile = away_profile
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    def _profile(self, possession: str) -> TeamPlayProfile:
        return self.home_profile if possession == self.home_team else self.away_profile

    def _other(self, possession: str) -> str:
        return self.away_team if possession == self.home_team else self.home_team

    def _clock_cost(self, profile: TeamPlayProfile, *, stopped: bool) -> int:
        if stopped:
            return int(self.rng.integers(5, 10))
        draw = int(round(self.rng.normal(profile.pace_seconds_mean, 5.0)))
        return max(12, min(45, draw))

    def _record_event(
        self,
        *,
        simulation_id: int,
        drive_id: int,
        play_id: int,
        seconds_before: int,
        seconds_after: int,
        possession: str,
        home_before: int,
        away_before: int,
        home_after: int,
        away_after: int,
        down: int,
        distance: int,
        yardline: int,
        play_type: str,
        yards: int,
        turnover_type: str | None = None,
        scoring_team: str | None = None,
        points: int = 0,
        drive_terminal: str | None = None,
    ) -> PlayEvent:
        return PlayEvent(
            game_id=self.game_id,
            simulation_id=simulation_id,
            drive_id=drive_id,
            play_id=play_id,
            quarter=_quarter(seconds_before),
            seconds_remaining_before=seconds_before,
            seconds_remaining_after=seconds_after,
            possession=possession,
            score_before_home=home_before,
            score_before_away=away_before,
            score_after_home=home_after,
            score_after_away=away_after,
            down=down,
            distance=distance,
            yardline=yardline,
            play_type=play_type,
            yards=int(yards),
            turnover_type=turnover_type,
            scoring_team=scoring_team,
            points=int(points),
            drive_terminal=drive_terminal,
        )

    def _simulate_one(self, simulation_id: int) -> GamePath:
        seconds = 3600
        possession = self.home_team if bool(self.rng.integers(0, 2)) else self.away_team
        yardline = 25
        down = 1
        distance = 10
        drive_id = 1
        play_id = 1
        home_score = 0
        away_score = 0
        quarter_points = {
            1: {self.home_team: 0, self.away_team: 0},
            2: {self.home_team: 0, self.away_team: 0},
            3: {self.home_team: 0, self.away_team: 0},
            4: {self.home_team: 0, self.away_team: 0},
        }
        events: list[PlayEvent] = []

        while seconds > 0:
            if play_id > 500:
                raise RuntimeError("ENGINE_A_MAX_PLAYS_EXCEEDED")
            profile = self._profile(possession)
            home_before, away_before = home_score, away_score
            quarter = _quarter(seconds)
            scoring_team: str | None = None
            points = 0
            turnover_type: str | None = None
            terminal: str | None = None
            yards = 0
            stopped_clock = False
            next_yardline: int | None = None

            # Fourth-down decision is part of the same path. This candidate uses
            # a conservative deterministic field-position rule; policy fitting
            # belongs to later validation, not hidden market-specific logic.
            if down == 4 and yardline >= 60:
                made = bool(self.rng.random() < profile.field_goal_make_prob)
                play_type = "FIELD_GOAL"
                stopped_clock = True
                if made:
                    scoring_team = possession
                    points = 3
                    terminal = "FIELD_GOAL_MADE"
                    next_yardline = 25
                else:
                    terminal = "FIELD_GOAL_MISSED"
                    next_yardline = max(20, min(80, 100 - yardline))
            elif down == 4 and yardline < 60 and self.rng.random() >= 0.16:
                play_type = "PUNT"
                stopped_clock = True
                terminal = "PUNT"
                # Coarse net-punt field position; the event remains explicit so
                # Engine C can later replace this candidate without changing path
                # identity/reconciliation semantics.
                next_yardline = 20
            else:
                if self.rng.random() < profile.pass_rate:
                    if self.rng.random() < profile.sack_rate:
                        play_type = "SACK"
                        yards = -max(1, int(round(abs(self.rng.normal(6.0, 3.0)))))
                    elif self.rng.random() < profile.interception_rate:
                        play_type = "INTERCEPTION"
                        yards = max(0, int(round(self.rng.normal(7.0, 6.0))))
                        turnover_type = "INTERCEPTION"
                        terminal = "TURNOVER"
                        stopped_clock = True
                    elif self.rng.random() < profile.completion_rate:
                        play_type = "PASS_COMPLETE"
                        yards = int(round(self.rng.normal(profile.completion_yards_mean, profile.completion_yards_sd)))
                        yards = max(-5, min(70, yards))
                    else:
                        play_type = "PASS_INCOMPLETE"
                        yards = 0
                        stopped_clock = True
                else:
                    play_type = "RUSH"
                    yards = int(round(self.rng.normal(profile.run_yards_mean, profile.run_yards_sd)))
                    yards = max(-8, min(45, yards))
                    if self.rng.random() < profile.fumble_rate:
                        turnover_type = "FUMBLE"
                        terminal = "TURNOVER"
                        stopped_clock = True

                new_yardline = yardline + yards
                if new_yardline <= 0:
                    scoring_team = self._other(possession)
                    points = 2
                    terminal = "SAFETY"
                    stopped_clock = True
                    next_yardline = 25
                elif new_yardline >= 100 and turnover_type is None:
                    scoring_team = possession
                    points = 7
                    terminal = "TOUCHDOWN"
                    stopped_clock = True
                    next_yardline = 25
                elif terminal == "TURNOVER":
                    next_yardline = max(5, min(95, 100 - _bounded_yardline(new_yardline)))
                else:
                    gained = yards
                    if gained >= distance:
                        yardline = _bounded_yardline(new_yardline)
                        down = 1
                        distance = max(1, min(10, 100 - yardline))
                    else:
                        yardline = _bounded_yardline(new_yardline)
                        down += 1
                        distance = max(1, distance - gained)

            cost = self._clock_cost(profile, stopped=stopped_clock)
            seconds_after = max(0, seconds - cost)

            if points:
                if scoring_team == self.home_team:
                    home_score += points
                elif scoring_team == self.away_team:
                    away_score += points
                else:
                    raise RuntimeError("SCORING_TEAM_INVALID")
                quarter_points[quarter][scoring_team] += points

            events.append(self._record_event(
                simulation_id=simulation_id,
                drive_id=drive_id,
                play_id=play_id,
                seconds_before=seconds,
                seconds_after=seconds_after,
                possession=possession,
                home_before=home_before,
                away_before=away_before,
                home_after=home_score,
                away_after=away_score,
                down=max(1, min(4, down if terminal is None else 4 if play_type in {"FIELD_GOAL", "PUNT"} else down)),
                distance=max(1, int(distance)),
                yardline=_bounded_yardline(yardline),
                play_type=play_type,
                yards=yards,
                turnover_type=turnover_type,
                scoring_team=scoring_team,
                points=points,
                drive_terminal=terminal,
            ))

            seconds = seconds_after
            play_id += 1

            if terminal is not None:
                possession = self._other(possession)
                drive_id += 1
                yardline = 25 if next_yardline is None else int(next_yardline)
                down = 1
                distance = max(1, min(10, 100 - yardline))

        path = GamePath(
            game_id=self.game_id,
            simulation_id=simulation_id,
            home_team=self.home_team,
            away_team=self.away_team,
            home_score=home_score,
            away_score=away_score,
            q1_home=quarter_points[1][self.home_team],
            q1_away=quarter_points[1][self.away_team],
            q2_home=quarter_points[2][self.home_team],
            q2_away=quarter_points[2][self.away_team],
            q3_home=quarter_points[3][self.home_team],
            q3_away=quarter_points[3][self.away_team],
            q4_home=quarter_points[4][self.home_team],
            q4_away=quarter_points[4][self.away_team],
            ot_home=0,
            ot_away=0,
            plays=tuple(events),
        )
        validate_game_path(path)
        return path

    def simulate(self, n: int) -> list[GamePath]:
        if n <= 0:
            return []
        return [self._simulate_one(i) for i in range(int(n))]


def validate_game_path(path: GamePath) -> None:
    """Hard structural acceptance checks for a single Engine-A path."""
    if not path.plays:
        raise ValueError("ENGINE_A_PATH_EMPTY")
    if any(event.game_id != path.game_id for event in path.plays):
        raise ValueError("ENGINE_A_GAME_ID_DRIFT")
    if any(event.simulation_id != path.simulation_id for event in path.plays):
        raise ValueError("ENGINE_A_SIMULATION_ID_DRIFT")
    if any(event.play_id != i for i, event in enumerate(path.plays, start=1)):
        raise ValueError("ENGINE_A_PLAY_ID_NONCONTIGUOUS")
    if any(event.quarter not in {1, 2, 3, 4} for event in path.plays):
        raise ValueError("ENGINE_A_QUARTER_INVALID")
    if any(event.seconds_remaining_after > event.seconds_remaining_before for event in path.plays):
        raise ValueError("ENGINE_A_CLOCK_REVERSED")
    if any(event.down < 1 or event.down > 4 for event in path.plays):
        raise ValueError("ENGINE_A_DOWN_INVALID")
    if any(event.distance < 1 for event in path.plays):
        raise ValueError("ENGINE_A_DISTANCE_INVALID")
    if any(event.yardline < 0 or event.yardline > 100 for event in path.plays):
        raise ValueError("ENGINE_A_YARDLINE_INVALID")

    home_event_points = sum(e.points for e in path.plays if e.scoring_team == path.home_team)
    away_event_points = sum(e.points for e in path.plays if e.scoring_team == path.away_team)
    if home_event_points != path.home_score or away_event_points != path.away_score:
        raise ValueError("ENGINE_A_SCORE_EVENT_RECONCILIATION_FAILED")

    if path.q1_home + path.q2_home != path.first_half_home_score:
        raise ValueError("ENGINE_A_HOME_FIRST_HALF_RECONCILIATION_FAILED")
    if path.q1_away + path.q2_away != path.first_half_away_score:
        raise ValueError("ENGINE_A_AWAY_FIRST_HALF_RECONCILIATION_FAILED")
    if path.q1_home + path.q2_home + path.q3_home + path.q4_home + path.ot_home != path.home_score:
        raise ValueError("ENGINE_A_HOME_FINAL_RECONCILIATION_FAILED")
    if path.q1_away + path.q2_away + path.q3_away + path.q4_away + path.ot_away != path.away_score:
        raise ValueError("ENGINE_A_AWAY_FINAL_RECONCILIATION_FAILED")
    if path.total != path.home_score + path.away_score:
        raise ValueError("ENGINE_A_TOTAL_RECONCILIATION_FAILED")
    if path.margin != path.home_score - path.away_score:
        raise ValueError("ENGINE_A_MARGIN_RECONCILIATION_FAILED")

    previous_home = 0
    previous_away = 0
    for event in path.plays:
        if event.score_before_home != previous_home or event.score_before_away != previous_away:
            raise ValueError("ENGINE_A_SCORE_CHAIN_BROKEN")
        if event.score_after_home < event.score_before_home or event.score_after_away < event.score_before_away:
            raise ValueError("ENGINE_A_SCORE_DECREASED")
        delta = (event.score_after_home - event.score_before_home) + (event.score_after_away - event.score_before_away)
        if delta != event.points:
            raise ValueError("ENGINE_A_EVENT_POINT_DELTA_MISMATCH")
        previous_home = event.score_after_home
        previous_away = event.score_after_away
    if previous_home != path.home_score or previous_away != path.away_score:
        raise ValueError("ENGINE_A_TERMINAL_SCORE_MISMATCH")
