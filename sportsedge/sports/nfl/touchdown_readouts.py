"""Research-only TD settlement over complete, scorer-bound scoring paths.

No scorer is inferred from a QB's passing TDs or from a team score. Every TD
must have exactly one stable scorer identity, including return/defensive/OT TDs.
These deterministic readouts do not fit or validate a probability engine.
"""
from collections import Counter
from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from sportsedge.core.simulate.football_path import FootballGamePath
from sportsedge.core.simulate.markets import derive_game_markets


TD_TYPES = frozenset({"TOUCHDOWN", "TOUCHDOWN_CANDIDATE", "DEFENSIVE_RETURN_TOUCHDOWN",
                      "DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE", "KICKOFF_RETURN_TD", "PUNT_RETURN_TD",
                      "OPENING_KICKOFF_RETURN_TOUCHDOWN"})
NON_TD_TYPES = frozenset({"FG_MADE", "FIELD_GOAL", "XP_MADE", "TWO_POINT_CONVERSION",
                          "TWO_POINT_MADE", "SAFETY", "SAFETY_CANDIDATE"})


@dataclass(frozen=True)
class ScorerBinding:
    player_id: str
    team: str


@dataclass(frozen=True)
class CompleteScorerPath:
    path: FootballGamePath
    scorers: Mapping[str, ScorerBinding]
    # Ordered event IDs are mandatory: clock ties cannot be resolved by an
    # arbitrary lexical event-ID order for first/last scorer settlement.
    ordered_event_ids: tuple[str, ...]
    settlement_scope: str
    participant_teams: Mapping[str, str]

    def touchdown_events(self):
        if self.settlement_scope != "FULL_GAME_INCLUDING_OVERTIME":
            raise ValueError("NFL_TD_COMPLETE_GAME_SCOPE_REQUIRED")
        self.path.assert_conservation()
        events = {event.event_id: event for event in self.path.events}
        if len(self.ordered_event_ids) != len(events) or set(self.ordered_event_ids) != set(events):
            raise ValueError("NFL_TD_COMPLETE_EVENT_ORDER_REQUIRED")
        ordered = [events[event_id] for event_id in self.ordered_event_ids]
        keys = [(event.period, -event.clock_seconds_remaining) for event in ordered]
        if keys != sorted(keys):
            raise ValueError("NFL_TD_EVENT_ORDER_INVALID")
        touchdowns = []
        for event in ordered:
            if event.score_type in TD_TYPES:
                if event.points != 6:
                    raise ValueError("NFL_TD_SEPARATE_TRY_EVENTS_REQUIRED")
                binding = self.scorers.get(event.event_id)
                if not isinstance(binding, ScorerBinding) or not binding.player_id.strip():
                    raise ValueError("NFL_TD_SCORER_IDENTITY_REQUIRED")
                if binding.team != event.team:
                    raise ValueError("NFL_TD_SCORER_TEAM_MISMATCH")
                if self.participant_teams.get(binding.player_id) != binding.team:
                    raise ValueError("NFL_TD_SCORER_PARTICIPATION_UNBOUND")
                touchdowns.append((event, binding))
            elif event.score_type not in NON_TD_TYPES:
                raise ValueError(f"NFL_TD_UNCLASSIFIED_SCORING_EVENT:{event.score_type}")
            else:
                expected_points = 3 if event.score_type in {"FG_MADE", "FIELD_GOAL"} else 1 if event.score_type == "XP_MADE" else 2
                if event.points != expected_points:
                    raise ValueError("NFL_TD_NON_TD_POINTS_INVALID")
        if set(self.scorers) != {event.event_id for event, _ in touchdowns}:
            raise ValueError("NFL_TD_SCORER_BINDING_COVERAGE_MISMATCH")
        return touchdowns


def derive_touchdown_readouts(paths, *, player_id: str, player_team: str,
                             td_line: float = 0.5, spread_line: float = 0.0,
                             total_line: float = 44.5) -> dict:
    """Compute TD markets and sides/totals from one sample, with push mass.

    No-TD games remain in the denominator and are returned as an explicit
    first/last-scorer outcome. Passing touchdowns do not credit the passer.
    Caller must bind player participation/void rules before any book settlement.
    """
    sample = list(paths)
    if not sample or any(not isinstance(p, CompleteScorerPath) for p in sample):
        raise ValueError("NFL_TD_COMPLETE_SCORER_PATHS_REQUIRED")
    if not isinstance(player_id, str) or not player_id.strip():
        raise ValueError("NFL_TD_PLAYER_ID_REQUIRED")
    for value in (td_line, spread_line, total_line):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError("NFL_TD_FINITE_NUMERIC_LINE_REQUIRED")
    if td_line < 0:
        raise ValueError("NFL_TD_NONNEGATIVE_LINE_REQUIRED")
    identities = {(p.path.game_id, p.path.home_team, p.path.away_team) for p in sample}
    if len(identities) != 1:
        raise ValueError("NFL_TD_GAME_IDENTITY_MISMATCH")
    if len({p.path.simulation_id for p in sample}) != len(sample):
        raise ValueError("NFL_TD_DUPLICATE_SIMULATION")
    if player_team not in (sample[0].path.home_team, sample[0].path.away_team):
        raise ValueError("NFL_TD_PLAYER_TEAM_INVALID")
    counts, first, last, team_totals, all_totals = [], [], [], [], []
    scorer_teams = {}
    for item in sample:
        if item.participant_teams.get(player_id) != player_team:
            raise ValueError("NFL_TD_PLAYER_PARTICIPATION_UNBOUND")
        touchdowns = item.touchdown_events()
        for _, scorer in touchdowns:
            prior = scorer_teams.setdefault(scorer.player_id, scorer.team)
            if prior != scorer.team or (scorer.player_id == player_id and scorer.team != player_team):
                raise ValueError("NFL_TD_PLAYER_IDENTITY_DRIFT")
        ids = [binding.player_id for _, binding in touchdowns]
        counts.append(ids.count(player_id))
        first.append(ids[0] if ids else None)
        last.append(ids[-1] if ids else None)
        team_totals.append(sum(event.team == player_team for event, _ in touchdowns))
        all_totals.append(len(touchdowns))
    n = len(sample)
    pmf = {count: frequency / n for count, frequency in sorted(Counter(counts).items())}
    return {
        "status": "RESEARCH_READOUT_NOT_MODEL_P", "sample_count": n,
        "model_p_created": False, "official_authority": False, "staking_authority": False,
        "promotion_authority": False, "player_id": player_id, "player_team": player_team,
        "td_count_pmf": pmf,
        "anytime_td": sum(x >= 1 for x in counts) / n,
        "two_plus_td": sum(x >= 2 for x in counts) / n,
        "three_plus_td": sum(x >= 3 for x in counts) / n,
        "td_total": {"over": sum(x > td_line for x in counts) / n,
                     "under": sum(x < td_line for x in counts) / n,
                     "push": sum(x == td_line for x in counts) / n},
        "first_td": sum(x == player_id for x in first) / n,
        "last_td": sum(x == player_id for x in last) / n,
        "no_touchdown": sum(x is None for x in first) / n,
        "team_td_count_pmf": {x: c / n for x, c in sorted(Counter(team_totals).items())},
        "game_td_count_pmf": {x: c / n for x, c in sorted(Counter(all_totals).items())},
        "game_markets": derive_game_markets([p.path.to_market_row() for p in sample],
                                            spread_line=spread_line, total_line=total_line),
        "settlement_requirement": "SOURCE_BOUND_PARTICIPATION_AND_BOOK_VOID_RULES_REQUIRED",
    }
