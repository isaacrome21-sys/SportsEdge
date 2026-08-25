"""Complete 2026 NFL regular-season OT transition composition.

This is the authoritative structural OT wrapper: opening and score kickoffs,
punts, turnovers, missed field goals, return touchdowns and subsequent scrimmage
opportunities all share one clock and one Rule 16 opportunity sequence.
"""

from __future__ import annotations

from .overtime import NFLRegularSeasonOTOpportunity, settle_nfl_regular_season_overtime
from .overtime_full_simulator import (
    NFLRegularSeasonFullOTSimulation,
    NFLRegularSeasonFullOTSimulator,
)
from .overtime_transitions import NFLRegularSeasonOTTransition


_CONTINUATION_ERRORS = {
    "OVERTIME_SECOND_OPPORTUNITY_REQUIRED",
    "OVERTIME_SUDDEN_DEATH_CONTINUATION_REQUIRED",
}


class NFLRegularSeasonCompleteOTSimulator(NFLRegularSeasonFullOTSimulator):
    """Full Rule 16 sequencing including scoring kickoffs and change-of-possession spots."""

    @staticmethod
    def _clone_kickoff_label(
        transition: NFLRegularSeasonOTTransition,
        *,
        label: str,
    ) -> NFLRegularSeasonOTTransition:
        prefix = "OPENING_KICKOFF"
        suffix = transition.transition_type[len(prefix):] if transition.transition_type.startswith(prefix) else f"_{transition.transition_type}"
        return NFLRegularSeasonOTTransition(
            transition_index=transition.transition_index,
            transition_type=f"{label}{suffix}",
            from_team=transition.from_team,
            receiving_team=transition.receiving_team,
            next_possession_team=transition.next_possession_team,
            next_yardline_100=transition.next_yardline_100,
            clock_seconds_remaining=transition.clock_seconds_remaining,
            points=transition.points,
            scoring_team=transition.scoring_team,
            creates_opportunity=transition.creates_opportunity,
            return_touchdown=transition.return_touchdown,
            return_yards=transition.return_yards,
            net_kick_yards=transition.net_kick_yards,
            opportunity_index=transition.opportunity_index,
        )

    def _score_kickoff(
        self,
        *,
        transition_index: int,
        opportunity_index: int,
        kicking_team: str,
        receiving_team: str,
        clock_seconds_remaining: int,
    ) -> NFLRegularSeasonOTTransition:
        transition = self._ot_transitions.opening_kickoff(
            transition_index=transition_index,
            opportunity_index=opportunity_index,
            kicking_team=kicking_team,
            receiving_team=receiving_team,
            clock_seconds_remaining=clock_seconds_remaining,
        )
        return self._clone_kickoff_label(transition, label="SCORE_KICKOFF")

    @staticmethod
    def _missed_fg_transition(
        *,
        transition_index: int,
        opportunity_index: int,
        kicking_team: str,
        receiving_team: str,
        clock_seconds_remaining: int,
        line_of_scrimmage_yardline_100: int,
    ) -> NFLRegularSeasonOTTransition:
        los = int(line_of_scrimmage_yardline_100)
        if not 1 <= los <= 99:
            raise ValueError("FULL_OT_MISSED_FG_YARDLINE_INVALID")
        kick_spot_distance_to_receiving_goal = los + 7
        next_yardline = (
            80
            if kick_spot_distance_to_receiving_goal <= 20
            else 100 - kick_spot_distance_to_receiving_goal
        )
        next_yardline = max(1, min(99, int(next_yardline)))
        return NFLRegularSeasonOTTransition(
            transition_index=transition_index,
            transition_type="MISSED_FIELD_GOAL",
            from_team=kicking_team,
            receiving_team=receiving_team,
            next_possession_team=receiving_team,
            next_yardline_100=next_yardline,
            clock_seconds_remaining=clock_seconds_remaining,
            opportunity_index=opportunity_index,
        )

    def _try_settle(self, opportunities):
        try:
            return settle_nfl_regular_season_overtime(
                self.regulation_path, tuple(opportunities)
            )
        except ValueError as exc:
            if str(exc) in _CONTINUATION_ERRORS:
                return None
            raise

    def _return_td_opportunity(
        self,
        transition: NFLRegularSeasonOTTransition,
        *,
        prior_opportunities: list[NFLRegularSeasonOTOpportunity],
    ) -> tuple[NFLRegularSeasonOTTransition, NFLRegularSeasonOTOpportunity]:
        if transition.opportunity_index is None:
            raise ValueError("FULL_OT_RETURN_TRANSITION_OPPORTUNITY_REQUIRED")
        team = transition.receiving_team
        try_points, _, _ = self._touchdown_try_points(
            team=team,
            opportunity_index=transition.opportunity_index,
            clock_remaining=transition.clock_seconds_remaining,
            prior_opportunities=prior_opportunities,
        )
        resolved = transition.with_points(6 + try_points, scoring_team=team)
        opportunity = NFLRegularSeasonOTOpportunity(
            transition.opportunity_index,
            team,
            team,
            6 + try_points,
            transition.clock_seconds_remaining,
            resolved.transition_type,
        )
        return resolved, opportunity

    def simulate(self) -> NFLRegularSeasonFullOTSimulation:
        regulation = self.regulation_path.to_scoring_path().to_market_row()
        if regulation["home_score"] != regulation["away_score"]:
            raise ValueError("OVERTIME_REQUIRES_TIED_REGULATION")

        home = self.regulation_path.base_path.home_team
        away = self.regulation_path.base_path.away_team
        receiver = home if self.rng.random() < 0.5 else away
        kicker = self._other(receiver)

        transitions: list[NFLRegularSeasonOTTransition] = []
        opportunities: list[NFLRegularSeasonOTOpportunity] = []
        plays = []
        next_play_index = 1
        next_transition_index = 1
        opportunity_index = 1
        clock_remaining = 600

        opening = self._ot_transitions.opening_kickoff(
            transition_index=next_transition_index,
            opportunity_index=opportunity_index,
            kicking_team=kicker,
            receiving_team=receiver,
            clock_seconds_remaining=clock_remaining,
        )
        next_transition_index += 1
        transitions.append(opening)
        clock_remaining = opening.clock_seconds_remaining

        if opening.return_touchdown:
            opening, opportunity = self._return_td_opportunity(
                opening, prior_opportunities=opportunities
            )
            transitions[-1] = opening
            opportunities.append(opportunity)
            current_team = None
            current_yardline = None
        else:
            current_team = receiver
            current_yardline = opening.next_yardline_100

        for _ in range(40):
            settlement = self._try_settle(opportunities) if opportunities else None
            if settlement is not None:
                result = NFLRegularSeasonFullOTSimulation(
                    self.regulation_path,
                    tuple(plays),
                    tuple(transitions),
                    tuple(opportunities),
                    settlement,
                )
                result.assert_reconciliation()
                return result

            # A scored opportunity with no direct possession transition must be
            # followed by a score kickoff to the opponent's next opportunity.
            if current_team is None:
                if not opportunities:
                    raise ValueError("FULL_OT_SCORE_KICKOFF_WITHOUT_PRIOR_OPPORTUNITY")
                last = opportunities[-1]
                if last.scoring_team is None or last.points <= 0:
                    raise ValueError("FULL_OT_CONTINUATION_TRANSITION_REQUIRED")
                kicking_team = last.scoring_team
                receiving_team = self._other(kicking_team)
                opportunity_index = len(opportunities) + 1
                kickoff = self._score_kickoff(
                    transition_index=next_transition_index,
                    opportunity_index=opportunity_index,
                    kicking_team=kicking_team,
                    receiving_team=receiving_team,
                    clock_seconds_remaining=clock_remaining,
                )
                next_transition_index += 1
                transitions.append(kickoff)
                clock_remaining = kickoff.clock_seconds_remaining
                if kickoff.return_touchdown:
                    kickoff, opportunity = self._return_td_opportunity(
                        kickoff, prior_opportunities=opportunities
                    )
                    transitions[-1] = kickoff
                    opportunities.append(opportunity)
                    current_team = None
                    current_yardline = None
                    continue
                current_team = receiving_team
                current_yardline = kickoff.next_yardline_100

            if current_yardline is None:
                raise ValueError("FULL_OT_START_YARDLINE_REQUIRED")
            opportunity_index = len(opportunities) + 1
            opportunity, new_plays, next_play_index, transition, next_transition_index = self._simulate_scrimmage_opportunity(
                opportunity_index=opportunity_index,
                team=current_team,
                clock_remaining=clock_remaining,
                prior_opportunities=opportunities,
                next_play_index=next_play_index,
                start_yardline_100=current_yardline,
                next_transition_index=next_transition_index,
            )
            opportunities.append(opportunity)
            plays.extend(new_plays)
            clock_remaining = opportunity.clock_end_seconds_remaining

            if transition is not None:
                transitions.append(transition)
                clock_remaining = transition.clock_seconds_remaining
                if transition.return_touchdown:
                    transition, return_opportunity = self._return_td_opportunity(
                        transition, prior_opportunities=opportunities
                    )
                    transitions[-1] = transition
                    opportunities.append(return_opportunity)
                    current_team = None
                    current_yardline = None
                else:
                    current_team = transition.next_possession_team
                    current_yardline = transition.next_yardline_100
                continue

            if opportunity.outcome_type == "MISSED_FIELD_GOAL":
                last_play = new_plays[-1] if new_plays else None
                if last_play is None or last_play.play_type != "FIELD_GOAL":
                    raise ValueError("FULL_OT_MISSED_FG_SOURCE_PLAY_REQUIRED")
                receiving_team = self._other(current_team)
                transition = self._missed_fg_transition(
                    transition_index=next_transition_index,
                    opportunity_index=opportunity_index + 1,
                    kicking_team=current_team,
                    receiving_team=receiving_team,
                    clock_seconds_remaining=clock_remaining,
                    line_of_scrimmage_yardline_100=last_play.yardline_100,
                )
                next_transition_index += 1
                transitions.append(transition)
                current_team = receiving_team
                current_yardline = transition.next_yardline_100
                continue

            # Made FG/offensive TD needs a score kickoff if settlement says the
            # other team is still owed an opportunity. Defensive return TDs and
            # safeties are settled before this branch when legally terminal.
            if opportunity.points > 0 and opportunity.scoring_team == current_team:
                current_team = None
                current_yardline = None
                continue

            # A non-scoring opportunity without an explicit possession transfer
            # cannot be safely continued by guessing a spot.
            current_team = None
            current_yardline = None

        raise ValueError("FULL_OT_OPPORTUNITY_LIMIT_EXCEEDED")
