from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from .live_card import CandidateMarket, LiveCardDecision, evaluate_live_card
from .live_inputs import LiveTournamentSnapshot
from .live_model import TournamentSimulationResult, simulate_remaining_tournament


@dataclass(frozen=True)
class LiveRunOutput:
    event: str
    round_number: int
    simulation_results: Mapping[str, TournamentSimulationResult]
    card: tuple[LiveCardDecision, ...]


def run_live_pga_model(
    *,
    snapshot: LiveTournamentSnapshot,
    candidates: Iterable[CandidateMarket],
    n_sims: int = 100_000,
    seed: int = 20260820,
    now: datetime | None = None,
    has_shot_level_data: bool = True,
) -> LiveRunOutput:
    """Run the live PGA state model, then price and Truth-Gate candidates.

    This function intentionally accepts normalized inputs only. Provider fetchers
    must verify identity and timestamps before constructing the snapshot.
    """
    if not snapshot.is_no_cut:
        raise ValueError(
            "run_live_pga_model currently supports no-cut events only; "
            "cut-rule simulation must be explicit rather than guessed"
        )

    simulation = simulate_remaining_tournament(
        snapshot.player_states(),
        rounds_remaining=snapshot.rounds_remaining,
        n_sims=n_sims,
        seed=seed,
    )

    card = evaluate_live_card(
        candidates,
        leaderboard_timestamp=snapshot.leaderboard_stamp.observed_at,
        tee_time_timestamp=snapshot.tee_times_stamp.observed_at,
        weather_timestamp=snapshot.weather_stamp.observed_at,
        market_timestamp=snapshot.market_stamp.observed_at,
        has_shot_level_data=has_shot_level_data,
        wd_status_verified=snapshot.wd_status_verified,
        market_rules_verified=snapshot.market_rules_verified,
        now=now,
    )

    return LiveRunOutput(
        event=snapshot.event,
        round_number=snapshot.round_number,
        simulation_results=simulation,
        card=card,
    )
