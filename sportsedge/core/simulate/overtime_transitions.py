"""Rule 16 overtime special-teams possession transitions.

This module is deliberately separate from the regulation field-position resolver:
regulation transitions are quarter 1-4 objects, while these transitions live in
the single 600-second overtime period. The resolver consumes the same field-
position and return-scoring profile inputs without inventing a separate market
model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .field_position import NFLFieldPositionProfile
from .return_scoring import NFLReturnScoringProfile, NFLReturnScoringResolver


@dataclass(frozen=True)
class NFLRegularSeasonOTTransition:
    transition_index: int
    transition_type: str
    from_team: str
    receiving_team: str
    next_possession_team: str
    next_yardline_100: int | None
    clock_seconds_remaining: int
    points: int = 0
    scoring_team: str | None = None
    creates_opportunity: bool = True
    return_touchdown: bool = False
    return_yards: int | None = None
    net_kick_yards: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.transition_index, bool) or not isinstance(self.transition_index, int) or self.transition_index <= 0:
            raise ValueError("OT_TRANSITION_INDEX_INVALID")
        if not str(self.transition_type).strip():
            raise ValueError("OT_TRANSITION_TYPE_REQUIRED")
        for team in (self.from_team, self.receiving_team, self.next_possession_team):
            if not str(team).strip():
                raise ValueError("OT_TRANSITION_TEAM_REQUIRED")
        if self.from_team == self.receiving_team:
            raise ValueError("OT_TRANSITION_TEAM_COLLISION")
        if self.next_possession_team != self.receiving_team:
            raise ValueError("OT_TRANSITION_NEXT_POSSESSION_MUST_BE_RECEIVER")
        if not 0 <= self.clock_seconds_remaining <= 600:
            raise ValueError("OT_TRANSITION_CLOCK_INVALID")
        if isinstance(self.points, bool) or not isinstance(self.points, int) or not 0 <= self.points <= 8:
            raise ValueError("OT_TRANSITION_POINTS_INVALID")
        if not isinstance(self.creates_opportunity, bool) or not isinstance(self.return_touchdown, bool):
            raise ValueError("OT_TRANSITION_BOOLEAN_INVALID")
        if self.points > 0 and not str(self.scoring_team or "").strip():
            raise ValueError("OT_TRANSITION_SCORING_TEAM_REQUIRED")
        if self.points == 0 and self.scoring_team is not None:
            raise ValueError("OT_ZERO_POINT_TRANSITION_HAS_SCORER")
        if self.return_touchdown:
            if self.points not in (6, 7, 8):
                raise ValueError("OT_RETURN_TOUCHDOWN_POINTS_INVALID")
            if self.scoring_team != self.receiving_team:
                raise ValueError("OT_RETURN_TOUCHDOWN_SCORER_INVALID")
            if self.next_yardline_100 is not None:
                raise ValueError("OT_SCORING_TRANSITION_HAS_NEXT_YARDLINE")
        elif self.points > 0:
            raise ValueError("OT_NON_RETURN_TRANSITION_HAS_POINTS")
        elif self.next_yardline_100 is None:
            raise ValueError("OT_NONSCORING_TRANSITION_YARDLINE_REQUIRED")
        elif not 1 <= self.next_yardline_100 <= 99:
            raise ValueError("OT_TRANSITION_YARDLINE_INVALID")
        if self.return_yards is not None and self.return_yards < 0:
            raise ValueError("OT_TRANSITION_RETURN_YARDS_INVALID")
        if self.net_kick_yards is not None and self.net_kick_yards < 0:
            raise ValueError("OT_TRANSITION_NET_KICK_YARDS_INVALID")


class NFLRegularSeasonOTTransitionResolver:
    """Seeded market-blind kickoff/punt resolver for the 10-minute OT period."""

    def __init__(
        self,
        home_field_position: NFLFieldPositionProfile,
        away_field_position: NFLFieldPositionProfile,
        home_return_scoring: NFLReturnScoringProfile,
        away_return_scoring: NFLReturnScoringProfile,
        *,
        seed: int | None = None,
    ) -> None:
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise ValueError("seed must be an integer")
        if home_field_position.team != home_return_scoring.team or away_field_position.team != away_return_scoring.team:
            raise ValueError("OT_TRANSITION_PROFILE_TEAM_MISMATCH")
        if home_field_position.team == away_field_position.team:
            raise ValueError("OT_TRANSITION_HOME_AWAY_COLLISION")
        self.home_field_position = home_field_position
        self.away_field_position = away_field_position
        self.home_return_scoring = home_return_scoring
        self.away_return_scoring = away_return_scoring
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self._return_scoring = NFLReturnScoringResolver(
            home_return_scoring,
            away_return_scoring,
            seed=self.seed + 1,
        )

    def _field(self, team: str) -> NFLFieldPositionProfile:
        if team == self.home_field_position.team:
            return self.home_field_position
        if team == self.away_field_position.team:
            return self.away_field_position
        raise ValueError(f"OT_TRANSITION_TEAM_NOT_FOUND:{team}")

    @staticmethod
    def _clock(clock_seconds_remaining: int) -> int:
        value = int(clock_seconds_remaining)
        if not 0 <= value <= 600:
            raise ValueError("OT_TRANSITION_CLOCK_INVALID")
        return value

    def opening_kickoff(
        self,
        *,
        transition_index: int,
        kicking_team: str,
        receiving_team: str,
        clock_seconds_remaining: int = 600,
    ) -> NFLRegularSeasonOTTransition:
        clock = self._clock(clock_seconds_remaining)
        if kicking_team == receiving_team:
            raise ValueError("OT_TRANSITION_TEAM_COLLISION")
        kicking = self._field(kicking_team)
        receiving = self._field(receiving_team)
        elapsed = min(clock, int(self.rng.integers(4, 9)))
        end_clock = clock - elapsed

        draw = self.rng.random()
        if draw < kicking.deep_touchback_rate:
            return NFLRegularSeasonOTTransition(
                transition_index, "OPENING_KICKOFF_TOUCHBACK_35",
                kicking_team, receiving_team, receiving_team, 65, end_clock,
            )
        if draw < kicking.deep_touchback_rate + kicking.landing_touchback_rate:
            return NFLRegularSeasonOTTransition(
                transition_index, "OPENING_KICKOFF_TOUCHBACK_20",
                kicking_team, receiving_team, receiving_team, 80, end_clock,
            )

        if self._return_scoring.is_touchdown(receiving_team, "KICKOFF"):
            return NFLRegularSeasonOTTransition(
                transition_index, "OPENING_KICKOFF_RETURN_TOUCHDOWN",
                kicking_team, receiving_team, receiving_team, None, end_clock,
                points=6, scoring_team=receiving_team, return_touchdown=True,
            )

        yards = int(round(self.rng.normal(
            receiving.kickoff_return_yards_mean,
            receiving.kickoff_return_yards_sd,
        )))
        yards = max(1, min(99, yards))
        return NFLRegularSeasonOTTransition(
            transition_index, "OPENING_KICKOFF_RETURN",
            kicking_team, receiving_team, receiving_team,
            max(1, min(99, 100 - yards)), end_clock,
            return_yards=yards,
        )

    def punt(
        self,
        *,
        transition_index: int,
        punting_team: str,
        receiving_team: str,
        clock_seconds_remaining: int,
        kicking_yardline_100: int,
    ) -> NFLRegularSeasonOTTransition:
        clock = self._clock(clock_seconds_remaining)
        if punting_team == receiving_team:
            raise ValueError("OT_TRANSITION_TEAM_COLLISION")
        yardline = int(kicking_yardline_100)
        if not 1 <= yardline <= 99:
            raise ValueError("OT_PUNT_YARDLINE_INVALID")
        punting = self._field(punting_team)
        elapsed = min(clock, int(self.rng.integers(6, 11)))
        end_clock = clock - elapsed
        net = int(round(self.rng.normal(punting.punt_net_yards_mean, punting.punt_net_yards_sd)))
        net = max(0, min(80, net))
        remaining_to_goal = yardline - net
        if remaining_to_goal <= 0:
            return NFLRegularSeasonOTTransition(
                transition_index, "PUNT_TOUCHBACK_20",
                punting_team, receiving_team, receiving_team, 80, end_clock,
                net_kick_yards=net,
            )

        if self._return_scoring.is_touchdown(receiving_team, "PUNT"):
            return NFLRegularSeasonOTTransition(
                transition_index, "PUNT_RETURN_TOUCHDOWN",
                punting_team, receiving_team, receiving_team, None, end_clock,
                points=6, scoring_team=receiving_team, return_touchdown=True,
                net_kick_yards=net,
            )

        next_yardline = max(1, min(99, 100 - remaining_to_goal))
        return NFLRegularSeasonOTTransition(
            transition_index, "PUNT_RETURN",
            punting_team, receiving_team, receiving_team, next_yardline, end_clock,
            net_kick_yards=net,
        )
