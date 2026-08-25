"""Structural Engine A football path contract.

This module is deliberately narrower than the final drive/play model in
``docs/football/FULL_MODEL_ORCHESTRATOR_SPEC.md``.  It establishes the first
production invariant: every game, half, quarter, margin and total read-out must
come from one shared ordered scoring-event path.  It does not claim predictive
promotion, player attribution, special-teams modeling, or validated NFL scoring
rates.

Historical/market lines and sportsbook prices are not accepted as simulator
inputs.  Expected team points are model outputs supplied by a market-blind
football feature/model layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


_REGULATION_PERIODS = (1, 2, 3, 4)
_ALL_PERIODS = (1, 2, 3, 4, 5)
_PERIOD_WEIGHTS = np.array([0.24, 0.26, 0.24, 0.26], dtype=float)
_TD_SHARE_OF_SCORING_EVENTS = 0.62
_TD_WITH_TRY_POINTS = 7
_FIELD_GOAL_POINTS = 3


@dataclass(frozen=True)
class ScoringEvent:
    """One immutable scoring event on a shared simulated game path."""

    event_id: str
    period: int
    clock_seconds_remaining: int
    team: str
    points: int
    score_type: str

    def __post_init__(self) -> None:
        if self.period not in _ALL_PERIODS:
            raise ValueError("INVALID_SCORING_PERIOD")
        if not 0 <= self.clock_seconds_remaining <= 900:
            raise ValueError("INVALID_SCORING_CLOCK")
        if isinstance(self.points, bool) or not isinstance(self.points, int) or self.points <= 0:
            raise ValueError("INVALID_SCORING_POINTS")
        if not self.event_id:
            raise ValueError("SCORING_EVENT_ID_REQUIRED")
        if not self.team:
            raise ValueError("SCORING_TEAM_REQUIRED")
        if not self.score_type:
            raise ValueError("SCORING_TYPE_REQUIRED")


@dataclass(frozen=True)
class FootballGamePath:
    """Immutable shared path from which all score-level markets are sliced."""

    game_id: str
    simulation_id: int
    home_team: str
    away_team: str
    events: tuple[ScoringEvent, ...]

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("GAME_ID_REQUIRED")
        if self.home_team == self.away_team:
            raise ValueError("HOME_AWAY_TEAM_COLLISION")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("DUPLICATE_SCORING_EVENT_ID")
        for event in self.events:
            if event.team not in (self.home_team, self.away_team):
                raise ValueError("SCORING_EVENT_TEAM_MISMATCH")

        expected_order = tuple(
            sorted(
                self.events,
                key=lambda event: (
                    event.period,
                    -event.clock_seconds_remaining,
                    event.event_id,
                ),
            )
        )
        if self.events != expected_order:
            raise ValueError("SCORING_EVENTS_OUT_OF_ORDER")

    def _points(self, team: str, periods: Iterable[int]) -> int:
        period_set = frozenset(int(period) for period in periods)
        return sum(
            event.points
            for event in self.events
            if event.team == team and event.period in period_set
        )

    def to_market_row(self) -> dict[str, int | str]:
        """Return one coherent score row for downstream deterministic read-outs."""

        quarter_home = {q: self._points(self.home_team, (q,)) for q in _REGULATION_PERIODS}
        quarter_away = {q: self._points(self.away_team, (q,)) for q in _REGULATION_PERIODS}
        ot_home = self._points(self.home_team, (5,))
        ot_away = self._points(self.away_team, (5,))

        first_half_home = quarter_home[1] + quarter_home[2]
        first_half_away = quarter_away[1] + quarter_away[2]
        second_half_reg_home = quarter_home[3] + quarter_home[4]
        second_half_reg_away = quarter_away[3] + quarter_away[4]
        second_half_with_ot_home = second_half_reg_home + ot_home
        second_half_with_ot_away = second_half_reg_away + ot_away
        home_score = first_half_home + second_half_with_ot_home
        away_score = first_half_away + second_half_with_ot_away

        return {
            "game_id": self.game_id,
            "simulation_id": self.simulation_id,
            "q1_home_score": quarter_home[1],
            "q1_away_score": quarter_away[1],
            "q2_home_score": quarter_home[2],
            "q2_away_score": quarter_away[2],
            "q3_home_score": quarter_home[3],
            "q3_away_score": quarter_away[3],
            "q4_home_score": quarter_home[4],
            "q4_away_score": quarter_away[4],
            "ot_home_score": ot_home,
            "ot_away_score": ot_away,
            "first_half_home_score": first_half_home,
            "first_half_away_score": first_half_away,
            "second_half_regulation_home_score": second_half_reg_home,
            "second_half_regulation_away_score": second_half_reg_away,
            "second_half_with_ot_home_score": second_half_with_ot_home,
            "second_half_with_ot_away_score": second_half_with_ot_away,
            # Compatibility aliases from the first Engine A slice. These mean
            # Q3+Q4+OT; callers pricing a second-half market must instead use the
            # explicit regulation/with-OT fields selected by settlement rules.
            "second_half_home_score": second_half_with_ot_home,
            "second_half_away_score": second_half_with_ot_away,
            "home_score": home_score,
            "away_score": away_score,
            "margin": home_score - away_score,
            "total": home_score + away_score,
        }

    def assert_conservation(self) -> None:
        """Fail closed if any score partition can diverge from the parent path."""

        row = self.to_market_row()
        if row["first_half_home_score"] != row["q1_home_score"] + row["q2_home_score"]:
            raise ValueError("ENGINE_A_HOME_FIRST_HALF_RECONCILIATION_FAILED")
        if row["first_half_away_score"] != row["q1_away_score"] + row["q2_away_score"]:
            raise ValueError("ENGINE_A_AWAY_FIRST_HALF_RECONCILIATION_FAILED")
        if row["second_half_regulation_home_score"] != row["q3_home_score"] + row["q4_home_score"]:
            raise ValueError("ENGINE_A_HOME_REGULATION_SECOND_HALF_RECONCILIATION_FAILED")
        if row["second_half_regulation_away_score"] != row["q3_away_score"] + row["q4_away_score"]:
            raise ValueError("ENGINE_A_AWAY_REGULATION_SECOND_HALF_RECONCILIATION_FAILED")
        if row["second_half_with_ot_home_score"] != row["second_half_regulation_home_score"] + row["ot_home_score"]:
            raise ValueError("ENGINE_A_HOME_SECOND_HALF_OT_RECONCILIATION_FAILED")
        if row["second_half_with_ot_away_score"] != row["second_half_regulation_away_score"] + row["ot_away_score"]:
            raise ValueError("ENGINE_A_AWAY_SECOND_HALF_OT_RECONCILIATION_FAILED")
        if row["second_half_home_score"] != row["second_half_with_ot_home_score"]:
            raise ValueError("ENGINE_A_HOME_SECOND_HALF_ALIAS_RECONCILIATION_FAILED")
        if row["second_half_away_score"] != row["second_half_with_ot_away_score"]:
            raise ValueError("ENGINE_A_AWAY_SECOND_HALF_ALIAS_RECONCILIATION_FAILED")
        if row["home_score"] != row["first_half_home_score"] + row["second_half_with_ot_home_score"]:
            raise ValueError("ENGINE_A_HOME_FINAL_RECONCILIATION_FAILED")
        if row["away_score"] != row["first_half_away_score"] + row["second_half_with_ot_away_score"]:
            raise ValueError("ENGINE_A_AWAY_FINAL_RECONCILIATION_FAILED")
        if row["total"] != row["home_score"] + row["away_score"]:
            raise ValueError("ENGINE_A_TOTAL_RECONCILIATION_FAILED")
        if row["margin"] != row["home_score"] - row["away_score"]:
            raise ValueError("ENGINE_A_MARGIN_RECONCILIATION_FAILED")

        home_event_points = sum(event.points for event in self.events if event.team == self.home_team)
        away_event_points = sum(event.points for event in self.events if event.team == self.away_team)
        if home_event_points != row["home_score"]:
            raise ValueError("ENGINE_A_HOME_EVENT_POINTS_RECONCILIATION_FAILED")
        if away_event_points != row["away_score"]:
            raise ValueError("ENGINE_A_AWAY_EVENT_POINTS_RECONCILIATION_FAILED")


class EngineAPathSimulator:
    """Seeded structural scoring-path challenger for Engine A.

    The generator creates ordered football scoring events rather than drawing a
    final score and independently splitting it into market periods. Touchdown
    and field-goal event rates are intentionally transparent candidate defaults;
    they require historical fit before any predictive/promotion claim.
    """

    def __init__(
        self,
        *,
        game_id: str,
        home_team: str,
        away_team: str,
        expected_home_points: float,
        expected_away_points: float,
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
        if expected_home_points < 0 or expected_away_points < 0:
            raise ValueError("EXPECTED_POINTS_MUST_BE_NONNEGATIVE")

        self.game_id = game_id
        self.home_team = home_team
        self.away_team = away_team
        self.expected_home_points = float(expected_home_points)
        self.expected_away_points = float(expected_away_points)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    @staticmethod
    def _conditional_scoring_points() -> float:
        return (
            _TD_SHARE_OF_SCORING_EVENTS * _TD_WITH_TRY_POINTS
            + (1.0 - _TD_SHARE_OF_SCORING_EVENTS) * _FIELD_GOAL_POINTS
        )

    def _team_events(
        self,
        *,
        simulation_id: int,
        team: str,
        expected_points: float,
    ) -> list[ScoringEvent]:
        if expected_points == 0:
            return []

        scoring_event_mean = expected_points / self._conditional_scoring_points()
        event_count = int(self.rng.poisson(scoring_event_mean))
        if event_count <= 0:
            return []

        periods = self.rng.choice(
            np.array(_REGULATION_PERIODS, dtype=int),
            size=event_count,
            p=_PERIOD_WEIGHTS,
        )
        clocks = self.rng.integers(0, 901, size=event_count)
        touchdown_flags = self.rng.random(event_count) < _TD_SHARE_OF_SCORING_EVENTS

        events: list[ScoringEvent] = []
        for index in range(event_count):
            touchdown = bool(touchdown_flags[index])
            points = _TD_WITH_TRY_POINTS if touchdown else _FIELD_GOAL_POINTS
            score_type = "TD_PLUS_TRY_CANDIDATE" if touchdown else "FIELD_GOAL_CANDIDATE"
            events.append(
                ScoringEvent(
                    event_id=f"{simulation_id}:{team}:{index}",
                    period=int(periods[index]),
                    clock_seconds_remaining=int(clocks[index]),
                    team=team,
                    points=points,
                    score_type=score_type,
                )
            )
        return events

    def _simulate_one(self, simulation_id: int) -> FootballGamePath:
        events = self._team_events(
            simulation_id=simulation_id,
            team=self.home_team,
            expected_points=self.expected_home_points,
        )
        events.extend(
            self._team_events(
                simulation_id=simulation_id,
                team=self.away_team,
                expected_points=self.expected_away_points,
            )
        )
        ordered = tuple(
            sorted(
                events,
                key=lambda event: (
                    event.period,
                    -event.clock_seconds_remaining,
                    event.event_id,
                ),
            )
        )
        path = FootballGamePath(
            game_id=self.game_id,
            simulation_id=simulation_id,
            home_team=self.home_team,
            away_team=self.away_team,
            events=ordered,
        )
        path.assert_conservation()
        return path

    def simulate(self, n: int) -> list[FootballGamePath]:
        if n <= 0:
            return []
        return [self._simulate_one(simulation_id) for simulation_id in range(int(n))]
