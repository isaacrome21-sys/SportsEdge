"""Coherent NFL team/player prop paths without invented game-script weights.

This module is the clean successor to the useful pieces of the old #1006/#1007
stack.  It deliberately does *not* map score margin to pass/rush multipliers with
hard-coded coefficients.  Each simulated game state must already contain
market-blind pass/rush multipliers from an upstream fitted or preregistered
source.  Those state values shift workload; the existing shared prop model still
owns role stabilization and single-player draw kernels.

For receiving props, QB completions and passing yards are allocated across the
provided receiver pool on the same path.  Completion weights come only from each
receiver's stabilized targets x catch rate.  The fitted QB yards/completion and
the catch-weighted receiver yards/reception inputs must agree before simulation;
the allocator will not silently repair inconsistent inputs by rescaling them.
Per-reception yard shapes mirror the existing shared-sim receiving kernel, then
integer rounding preserves exact path-level QB/receiver yard identity.

For anytime TD, this module accepts explicit per-player TD opportunity shares.
It does not recreate the old 50/50 rush/goal-line and target/close-target blend.
The caller must supply fitted/preregistered shares; any residual share belongs to
an unmodeled OTHER scorer.

Sportsbook/market inputs are rejected recursively.  This is research plumbing:
it grants no Model_P, Truth Gate, staking, promotion, OFFICIAL, or evidence-clock
authority.
"""
from __future__ import annotations

from math import floor, isclose, isfinite
import random
from typing import Any, Mapping, Sequence

from sportsedge.nfl_prop_shared_sim import (
    FORBIDDEN_MARKET_KEYS,
    FORBIDDEN_MARKET_KEY_FRAGMENTS,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    NflPropSimulationError,
    simulate_player,
    stabilized_role,
)


SCRIPT_KEYS = ("pass_multiplier", "rush_multiplier")
_SCRIPT_SOURCE_FORBIDDEN = ("market", "sportsbook", "odds", "price", "vig")


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPropSimulationError(f"{name}:NONFINITE")
    return out


def _looks_like_market_key(key: str) -> bool:
    lowered = str(key).lower()
    if lowered in FORBIDDEN_MARKET_KEYS:
        return True
    return any(fragment in lowered for fragment in FORBIDDEN_MARKET_KEY_FRAGMENTS)


def _assert_no_market_inputs(node: Any) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if _looks_like_market_key(str(key)):
                raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
            _assert_no_market_inputs(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _assert_no_market_inputs(value)


def _context_multiplier(payload: Mapping[str, Any], key: str) -> float:
    context = payload.get("context") or {}
    if not isinstance(context, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    value = _num(context.get(key, 1.0), f"context.{key}")
    if value < MULTIPLIER_MIN or value > MULTIPLIER_MAX:
        raise NflPropSimulationError(f"CONTEXT_MULTIPLIER_OUT_OF_RANGE:{key}")
    return value


def _sigma(payload: Mapping[str, Any]) -> float:
    context = payload.get("context") or {}
    if not isinstance(context, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    value = _num(context.get("shared_workload_sigma", 0.12), "context.shared_workload_sigma")
    if value < 0:
        raise NflPropSimulationError("SHARED_SIGMA_INVALID")
    return value


def _absorbed_role(payload: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    """Fold non-script pregame context into the stabilized role.

    ``pass_multiplier`` and ``rush_multiplier`` are reserved for the explicit
    game-state script in this coherent path.  A non-neutral value in player
    context would otherwise multiply the same concept twice, so it fails closed.
    """
    _assert_no_market_inputs(payload)
    role = dict(stabilized_role(payload))
    volume = _context_multiplier(payload, "volume_multiplier")
    pass_mult = _context_multiplier(payload, "pass_multiplier")
    rush_mult = _context_multiplier(payload, "rush_multiplier")
    target_mult = _context_multiplier(payload, "target_multiplier")
    efficiency = _context_multiplier(payload, "efficiency_multiplier")
    pass_eff = _context_multiplier(payload, "pass_efficiency_multiplier")
    rush_eff = _context_multiplier(payload, "rush_efficiency_multiplier")
    recv_eff = _context_multiplier(payload, "receiving_efficiency_multiplier")

    if abs(pass_mult - 1.0) > 1e-12 or abs(rush_mult - 1.0) > 1e-12:
        raise NflPropSimulationError("CONTEXT_SCRIPT_MULTIPLIER_CONFLICT")

    role["pass_attempts"] *= volume
    role["rush_attempts"] *= volume
    role["targets"] *= volume * target_mult
    role["pass_yards_per_completion"] *= efficiency * pass_eff
    role["rush_yards_per_attempt"] *= efficiency * rush_eff
    role["receiving_yards_per_reception"] *= efficiency * recv_eff
    return role, _sigma(payload)


def _script_state(state: Mapping[str, Any]) -> tuple[float, float]:
    _assert_no_market_inputs(state)
    source = str(state.get("script_source", "")).strip().lower()
    if not source:
        raise NflPropSimulationError("SCRIPT_SOURCE_REQUIRED")
    if any(token in source for token in _SCRIPT_SOURCE_FORBIDDEN):
        raise NflPropSimulationError("SCRIPT_SOURCE_NOT_MARKET_BLIND")

    values: list[float] = []
    for key in SCRIPT_KEYS:
        if key not in state:
            raise NflPropSimulationError(f"SCRIPT_MULTIPLIER_REQUIRED:{key}")
        value = _num(state[key], key)
        if value < MULTIPLIER_MIN or value > MULTIPLIER_MAX:
            raise NflPropSimulationError(f"SCRIPT_MULTIPLIER_OUT_OF_RANGE:{key}")
        values.append(value)
    return values[0], values[1]


def _scripted_role(payload: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    role, sigma = _absorbed_role(payload)
    pass_mult, rush_mult = _script_state(state)
    role["pass_attempts"] *= pass_mult
    role["targets"] *= pass_mult
    role["rush_attempts"] *= rush_mult
    return role, sigma


def scripted_role_means(payload: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, float]:
    """Expose deterministic post-context, post-script workload means for audit/tests."""
    role, _ = _scripted_role(payload, state)
    return {
        "pass_attempts": role["pass_attempts"],
        "rush_attempts": role["rush_attempts"],
        "targets": role["targets"],
    }


def _neutral_payload(role: Mapping[str, float], sigma: float) -> dict[str, Any]:
    return {
        "role_prior": dict(role),
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": sigma},
    }


def _player_name(payload: Mapping[str, Any]) -> str:
    name = str(payload.get("player", "")).strip()
    if not name:
        raise NflPropSimulationError("PLAYER_IDENTITY_REQUIRED")
    return name


def _weighted_index(rng: random.Random, weights: Sequence[float]) -> int:
    total = sum(weights)
    if total <= 0:
        raise NflPropSimulationError("RECEIVER_WEIGHT_REQUIRED")
    cut = rng.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if cut < running:
            return index
    return len(weights) - 1


def _integer_scale(total: int, names: Sequence[str], raw: Mapping[str, float]) -> dict[str, int]:
    if total < 0:
        raise NflPropSimulationError("PASSING_YARDS_NEGATIVE")
    if total == 0:
        return {name: 0 for name in names}
    raw_total = sum(max(0.0, float(raw[name])) for name in names)
    if raw_total <= 0:
        raise NflPropSimulationError("RECEIVING_YARD_WEIGHT_REQUIRED")

    exact = {name: total * max(0.0, float(raw[name])) / raw_total for name in names}
    base = {name: int(floor(exact[name])) for name in names}
    remainder = total - sum(base.values())
    ranked = sorted(
        enumerate(names),
        key=lambda pair: (-(exact[pair[1]] - base[pair[1]]), pair[0]),
    )
    for _, name in ranked[:remainder]:
        base[name] += 1
    return base


def _assert_yardage_identity(
    qb_role: Mapping[str, float],
    receiver_roles: Sequence[Mapping[str, float]],
    catch_weights: Sequence[float],
) -> None:
    """Require fitted QB YPC to equal catch-weighted receiver YPR.

    These are two views of the same completed-pass yardage identity.  If they do
    not agree, silently scaling receiver yard shapes to the QB total would hide a
    model-input contradiction, so the path fails closed.
    """
    total_weight = sum(catch_weights)
    if total_weight <= 0:
        return
    pooled_ypr = sum(
        weight * role["receiving_yards_per_reception"]
        for weight, role in zip(catch_weights, receiver_roles)
    ) / total_weight
    qb_ypc = qb_role["pass_yards_per_completion"]
    if not isclose(pooled_ypr, qb_ypc, rel_tol=1e-9, abs_tol=1e-9):
        raise NflPropSimulationError("YARDAGE_IDENTITY_MISMATCH")


def simulate_team_on_game_paths(
    qb_payload: Mapping[str, Any],
    receivers: Sequence[Mapping[str, Any]],
    game_states: Sequence[Mapping[str, Any]],
    *,
    seed: int = 21,
) -> list[dict[str, Any]]:
    """Simulate one coherent QB/receiver board for each supplied game-state path.

    The receiver pool must be exhaustive for the modeled passing offense.  If the
    caller does not model every named receiver, include an explicit synthetic
    ``OTHER`` receiver bucket with a real role estimate so all QB completions and
    passing yards still have somewhere truthful to land.
    """
    if not receivers:
        raise NflPropSimulationError("RECEIVERS_REQUIRED")
    if not game_states:
        raise NflPropSimulationError("GAME_STATES_REQUIRED")
    _assert_no_market_inputs(qb_payload)
    _assert_no_market_inputs(receivers)
    _assert_no_market_inputs(game_states)

    names = [_player_name(receiver) for receiver in receivers]
    if len(set(names)) != len(names):
        raise NflPropSimulationError("RECEIVER_IDENTITY_DUPLICATE")

    rng = random.Random(int(seed))
    games: list[dict[str, Any]] = []
    for state in game_states:
        qb_role, qb_sigma = _scripted_role(qb_payload, state)
        qb_seed = rng.randrange(0, 2**63)
        qb_draw = simulate_player(
            _neutral_payload(qb_role, qb_sigma),
            n_sims=1,
            seed=qb_seed,
        )[0]

        receiver_roles: list[dict[str, float]] = []
        receiver_draws: dict[str, dict[str, int]] = {}
        catch_weights: list[float] = []
        for name, receiver in zip(names, receivers):
            role, sigma = _scripted_role(receiver, state)
            receiver_roles.append(role)
            catch_weights.append(role["targets"] * role["catch_rate"])
            child_seed = rng.randrange(0, 2**63)
            receiver_draws[name] = simulate_player(
                _neutral_payload(role, sigma),
                n_sims=1,
                seed=child_seed,
            )[0]

        _assert_yardage_identity(qb_role, receiver_roles, catch_weights)

        completions = int(qb_draw["completions"])
        reception_counts = {name: 0 for name in names}
        if completions and sum(catch_weights) <= 0:
            raise NflPropSimulationError("RECEIVER_WEIGHT_REQUIRED")
        for _ in range(completions):
            index = _weighted_index(rng, catch_weights)
            reception_counts[names[index]] += 1

        raw_yards: dict[str, float] = {name: 0.0 for name in names}
        for name, role in zip(names, receiver_roles):
            mean = role["receiving_yards_per_reception"]
            for _ in range(reception_counts[name]):
                if mean > 0:
                    raw_yards[name] += rng.gammavariate(2.0, mean / 2.0)

        yard_alloc = _integer_scale(int(qb_draw["passing_yards"]), names, raw_yards)
        for name in names:
            draw = receiver_draws[name]
            draw["receptions"] = reception_counts[name]
            draw["receiving_yards"] = yard_alloc[name]
            draw["rush_receiving_yards"] = draw["rushing_yards"] + yard_alloc[name]

        if sum(draw["receptions"] for draw in receiver_draws.values()) != qb_draw["completions"]:
            raise NflPropSimulationError("COMPLETION_ALLOCATION_BROKEN")
        if sum(draw["receiving_yards"] for draw in receiver_draws.values()) != qb_draw["passing_yards"]:
            raise NflPropSimulationError("PASSING_YARD_ALLOCATION_BROKEN")

        games.append({"qb": qb_draw, "receivers": receiver_draws})
    return games


def simulate_anytime_td_board_on_game_paths(
    player_td_shares: Sequence[Mapping[str, Any]],
    game_states: Sequence[Mapping[str, Any]],
    *,
    seed: int = 21,
) -> list[dict[str, int]]:
    """Allocate team TDs to players using explicit fitted/preregistered shares.

    ``td_share`` values are unconditional shares of a team TD opportunity.  They
    may sum to less than one; the residual is an unmodeled OTHER scorer.  They may
    not sum above one.  No rush/target blending weights are created here.
    """
    if not player_td_shares:
        raise NflPropSimulationError("TD_SHARES_REQUIRED")
    if not game_states:
        raise NflPropSimulationError("GAME_STATES_REQUIRED")
    _assert_no_market_inputs(player_td_shares)
    _assert_no_market_inputs(game_states)

    names: list[str] = []
    shares: list[float] = []
    for row in player_td_shares:
        name = _player_name(row)
        if name in names:
            raise NflPropSimulationError("TD_SHARE_IDENTITY_DUPLICATE")
        share = _num(row.get("td_share"), f"td_share:{name}")
        if share < 0 or share > 1:
            raise NflPropSimulationError(f"TD_SHARE_OUT_OF_RANGE:{name}")
        names.append(name)
        shares.append(share)
    if sum(shares) > 1.0 + 1e-12:
        raise NflPropSimulationError("TD_SHARES_SUM_ABOVE_ONE")

    rng = random.Random(int(seed))
    outcomes: list[dict[str, int]] = []
    for state in game_states:
        _script_state(state)
        raw_team_tds = state.get("team_tds")
        if isinstance(raw_team_tds, bool):
            raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED")
        try:
            team_tds = int(raw_team_tds)
        except (TypeError, ValueError) as exc:
            raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED") from exc
        if team_tds < 0 or raw_team_tds != team_tds:
            raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED")

        hit = {name: 0 for name in names}
        for _ in range(team_tds):
            cut = rng.random()
            running = 0.0
            for name, share in zip(names, shares):
                running += share
                if cut < running:
                    hit[name] = 1
                    break
        outcomes.append(hit)
    return outcomes
