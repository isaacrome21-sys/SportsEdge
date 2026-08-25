"""NFL regular-season overtime Rule 16 settlement contract.

This module encodes rule/settlement state over already-resolved regulation paths.
It intentionally does not generate hidden market outcomes. Predictive overtime
play generation remains a separate Engine A+C task so rule correctness can be
validated independently from model parameters.

The regular-season contract is one 10-minute period. Both teams receive an
opportunity to possess once, subject to the kickoff-safety exception. A defense
that intercepts or recovers a loose ball has possession; therefore a defensive
return touchdown on the first credited opportunity also satisfies the scoring
club's opportunity before the terminal score comparison is applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .football_path import FootballGamePath, ScoringEvent
from .special_teams import ResolvedFootballPath


_OT_PERIOD_SECONDS = 600


@dataclass(frozen=True)
class NFLRegularSeasonOTOpportunity:
    """One completed Rule 16 possession-opportunity state.

    ``opportunity_team`` is the team credited with the opportunity at the start
    of this state. It is deliberately distinct from ``scoring_team`` so kickoff
    recoveries, defensive scores and the opening-kickoff safety exception can be
    represented without pretending the credited team necessarily scored.
    """

    opportunity_index: int
    opportunity_team: str
    scoring_team: str | None
    points: int
    clock_end_seconds_remaining: int
    outcome_type: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.opportunity_index, bool)
            or not isinstance(self.opportunity_index, int)
            or self.opportunity_index <= 0
        ):
            raise ValueError("OVERTIME_OPPORTUNITY_INDEX_INVALID")
        if not str(self.opportunity_team).strip():
            raise ValueError("OVERTIME_OPPORTUNITY_TEAM_REQUIRED")
        if self.scoring_team is not None and not str(self.scoring_team).strip():
            raise ValueError("OVERTIME_SCORING_TEAM_INVALID")
        if isinstance(self.points, bool) or not isinstance(self.points, int) or not 0 <= self.points <= 8:
            raise ValueError("OVERTIME_POINTS_INVALID")
        if not 0 <= self.clock_end_seconds_remaining <= _OT_PERIOD_SECONDS:
            raise ValueError("OVERTIME_CLOCK_INVALID")
        if not str(self.outcome_type).strip():
            raise ValueError("OVERTIME_OUTCOME_TYPE_REQUIRED")
        if self.points == 0 and self.scoring_team is not None:
            raise ValueError("OVERTIME_ZERO_POINTS_HAS_SCORING_TEAM")
        if self.points > 0 and self.scoring_team is None:
            raise ValueError("OVERTIME_POSITIVE_POINTS_SCORING_TEAM_REQUIRED")
        if self.outcome_type == "KICKOFF_SAFETY" and self.points != 2:
            raise ValueError("OVERTIME_KICKOFF_SAFETY_POINTS_INVALID")
        if self.outcome_type == "DEFENSIVE_RETURN_TOUCHDOWN" and self.points != 6:
            raise ValueError("OVERTIME_DEFENSIVE_RETURN_TD_POINTS_INVALID")
        if self.outcome_type == "DEFENSIVE_RETURN_TOUCHDOWN" and self.scoring_team == self.opportunity_team:
            raise ValueError("OVERTIME_DEFENSIVE_RETURN_TD_TEAM_INVALID")


@dataclass(frozen=True)
class NFLRegularSeasonOvertimeResult:
    regulation_path: ResolvedFootballPath
    opportunities: tuple[NFLRegularSeasonOTOpportunity, ...]
    winner: str | None
    tie: bool
    final_clock_seconds_remaining: int

    def __post_init__(self) -> None:
        if self.tie and self.winner is not None:
            raise ValueError("OVERTIME_RESULT_WINNER_TIE_COLLISION")
        if not self.tie and self.winner is None:
            raise ValueError("OVERTIME_RESULT_TERMINAL_WINNER_REQUIRED")
        if self.winner is not None and self.winner not in {
            self.regulation_path.base_path.home_team,
            self.regulation_path.base_path.away_team,
        }:
            raise ValueError("OVERTIME_RESULT_WINNER_TEAM_INVALID")
        if not 0 <= self.final_clock_seconds_remaining <= _OT_PERIOD_SECONDS:
            raise ValueError("OVERTIME_RESULT_CLOCK_INVALID")

    def to_scoring_path(self) -> FootballGamePath:
        """Append settled OT scores to the exact resolved regulation path."""

        events = list(self.regulation_path.to_scoring_path().events)
        for opportunity in self.opportunities:
            if opportunity.points <= 0:
                continue
            assert opportunity.scoring_team is not None
            events.append(
                ScoringEvent(
                    event_id=(
                        f"{self.regulation_path.base_path.simulation_id}:ot:"
                        f"{opportunity.opportunity_index:03d}"
                    ),
                    period=5,
                    clock_seconds_remaining=opportunity.clock_end_seconds_remaining,
                    team=opportunity.scoring_team,
                    points=opportunity.points,
                    score_type=f"NFL_OT_{opportunity.outcome_type}",
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
            game_id=self.regulation_path.base_path.game_id,
            simulation_id=self.regulation_path.base_path.simulation_id,
            home_team=self.regulation_path.base_path.home_team,
            away_team=self.regulation_path.base_path.away_team,
            events=ordered,
        )
        path.assert_conservation()
        return path


def _score_leader(scores: dict[str, int]) -> str | None:
    teams = list(scores)
    if scores[teams[0]] == scores[teams[1]]:
        return None
    return teams[0] if scores[teams[0]] > scores[teams[1]] else teams[1]


def _require_terminal_is_last(position: int, data: tuple[NFLRegularSeasonOTOpportunity, ...]) -> None:
    if position != len(data) - 1:
        raise ValueError("OVERTIME_EVENTS_AFTER_GAME_END")


def settle_nfl_regular_season_overtime(
    regulation_path: ResolvedFootballPath,
    opportunities: Iterable[NFLRegularSeasonOTOpportunity],
) -> NFLRegularSeasonOvertimeResult:
    """Settle a terminal 2026 NFL regular-season overtime sequence."""

    if not isinstance(regulation_path, ResolvedFootballPath):
        raise TypeError("RESOLVED_REGULATION_PATH_REQUIRED")
    data = tuple(opportunities)
    if not data:
        raise ValueError("OVERTIME_OPPORTUNITIES_REQUIRED")

    regulation_row = regulation_path.to_scoring_path().to_market_row()
    if regulation_row["home_score"] != regulation_row["away_score"]:
        raise ValueError("OVERTIME_REQUIRES_TIED_REGULATION")

    home = regulation_path.base_path.home_team
    away = regulation_path.base_path.away_team
    teams = {home, away}
    expected_indexes = tuple(range(1, len(data) + 1))
    if tuple(item.opportunity_index for item in data) != expected_indexes:
        raise ValueError("OVERTIME_OPPORTUNITY_INDEX_SEQUENCE_INVALID")

    previous_clock = _OT_PERIOD_SECONDS
    for item in data:
        if item.opportunity_team not in teams:
            raise ValueError("OVERTIME_OPPORTUNITY_TEAM_NOT_IN_GAME")
        if item.scoring_team is not None and item.scoring_team not in teams:
            raise ValueError("OVERTIME_SCORING_TEAM_NOT_IN_GAME")
        if item.clock_end_seconds_remaining > previous_clock:
            raise ValueError("OVERTIME_CLOCK_ORDER_INVALID")
        previous_clock = item.clock_end_seconds_remaining

    if len(data) >= 2 and data[1].opportunity_team == data[0].opportunity_team:
        raise ValueError("OVERTIME_SECOND_OPPORTUNITY_TEAM_INVALID")

    scores = {home: 0, away: 0}
    credited: set[str] = set()
    both_opportunities_reached = False

    for position, item in enumerate(data):
        credited.add(item.opportunity_team)
        if item.outcome_type == "DEFENSIVE_RETURN_TOUCHDOWN":
            assert item.scoring_team is not None
            credited.add(item.scoring_team)
        if item.points > 0:
            assert item.scoring_team is not None
            scores[item.scoring_team] += item.points

        if position == 0 and item.outcome_type == "KICKOFF_SAFETY":
            if item.scoring_team == item.opportunity_team:
                raise ValueError("OVERTIME_KICKOFF_SAFETY_TEAM_INVALID")
            assert item.scoring_team is not None
            _require_terminal_is_last(position, data)
            return NFLRegularSeasonOvertimeResult(
                regulation_path=regulation_path,
                opportunities=data,
                winner=item.scoring_team,
                tie=False,
                final_clock_seconds_remaining=item.clock_end_seconds_remaining,
            )

        if item.clock_end_seconds_remaining == 0:
            leader = _score_leader(scores)
            _require_terminal_is_last(position, data)
            return NFLRegularSeasonOvertimeResult(
                regulation_path=regulation_path,
                opportunities=data,
                winner=leader,
                tie=leader is None,
                final_clock_seconds_remaining=0,
            )

        if len(credited) == 2 and not both_opportunities_reached:
            both_opportunities_reached = True
            leader = _score_leader(scores)
            if leader is not None:
                _require_terminal_is_last(position, data)
                return NFLRegularSeasonOvertimeResult(
                    regulation_path=regulation_path,
                    opportunities=data,
                    winner=leader,
                    tie=False,
                    final_clock_seconds_remaining=item.clock_end_seconds_remaining,
                )
            continue

        if both_opportunities_reached and item.points > 0:
            assert item.scoring_team is not None
            _require_terminal_is_last(position, data)
            return NFLRegularSeasonOvertimeResult(
                regulation_path=regulation_path,
                opportunities=data,
                winner=item.scoring_team,
                tie=False,
                final_clock_seconds_remaining=item.clock_end_seconds_remaining,
            )

    if len(credited) < 2:
        raise ValueError("OVERTIME_SECOND_OPPORTUNITY_REQUIRED")
    raise ValueError("OVERTIME_SUDDEN_DEATH_CONTINUATION_REQUIRED")
