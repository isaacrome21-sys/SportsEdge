"""Couple NFL player prop simulations to one shared game-state path.

This is a transparent adapter for the MySpariEdge-like product direction: game
script, workload and player props move together, while sportsbook prices remain
outside model probability generation. It intentionally does not claim any
proprietary Spari Edge coefficients or hidden weights.
"""
from __future__ import annotations

from math import exp, isfinite
import random
from typing import Any, Mapping, Sequence

from sportsedge.nfl_prop_shared_sim import NflPropSimulationError, simulate_player

FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability",
})


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(x):
        raise NflPropSimulationError(f"{name}:NONFINITE")
    return x


def game_script_multipliers(state: Mapping[str, Any]) -> dict[str, float]:
    """Map a pre-market game-state draw to bounded pass/rush/target multipliers."""
    if FORBIDDEN_MARKET_KEYS.intersection(state):
        raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
    margin = _num(state.get("team_margin", 0.0), "team_margin")
    pace = _num(state.get("pace_multiplier", 1.0), "pace_multiplier")
    if pace <= 0:
        raise NflPropSimulationError("PACE_POSITIVE_REQUIRED")
    # Smooth bounded script response: trailing raises pass/target volume; leading
    # raises rush volume. Constants are transparent engineering defaults, not fits.
    trail = 1.0 / (1.0 + exp(margin / 7.0))
    lead = 1.0 - trail
    return {
        "volume_multiplier": pace,
        "pass_multiplier": 0.88 + 0.24 * trail,
        "target_multiplier": 0.90 + 0.20 * trail,
        "rush_multiplier": 0.88 + 0.24 * lead,
    }


def simulate_player_on_game_paths(
    payload: Mapping[str, Any],
    game_states: Sequence[Mapping[str, Any]],
    *,
    seed: int = 21,
) -> list[dict[str, int]]:
    """Produce one player draw per shared game-state draw, deterministically."""
    if FORBIDDEN_MARKET_KEYS.intersection(payload):
        raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
    if not game_states:
        raise NflPropSimulationError("GAME_STATES_REQUIRED")
    base_context = payload.get("context") or {}
    if not isinstance(base_context, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    rng = random.Random(int(seed))
    out: list[dict[str, int]] = []
    for state in game_states:
        script = game_script_multipliers(state)
        context = dict(base_context)
        for key, value in script.items():
            context[key] = _num(context.get(key, 1.0), f"context.{key}") * value
        row = dict(payload)
        row["context"] = context
        child_seed = rng.randrange(0, 2**63)
        out.append(simulate_player(row, n_sims=1, seed=child_seed)[0])
    return out
