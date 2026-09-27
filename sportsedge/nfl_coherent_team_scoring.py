"""Coherent NFL team scoring on the same paths as QB/receiver props.

This layer consumes the yardage/reception/carry paths from
``nfl_coherent_team_props`` and allocates the same path's team touchdowns without
creating independent player-TD worlds.

The caller supplies an already fitted/script-adjusted ``pass_td_share`` on each
game state.  No score-margin coefficient or hidden adjustment is invented here.
Player rows supply fitted ``receiving_td_share`` / ``rushing_td_share`` weights.
Those weights are combined with the *realized path capacity* (receptions or rush
attempts), so a player cannot receive a passing TD without a catch and cannot be
allocated more TD events than the relevant path opportunities.

This is research plumbing only.  It grants no Model_P, Truth Gate, staking,
promotion, OFFICIAL, or evidence-clock authority.
"""
from __future__ import annotations

from math import comb, isfinite
import random
from typing import Any, Mapping, Sequence

from sportsedge.nfl_coherent_team_props import simulate_team_on_game_paths
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError


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


def _share(row: Mapping[str, Any], key: str, identity: str) -> float:
    if key not in row:
        raise NflPropSimulationError(f"{key.upper()}_REQUIRED:{identity}")
    value = _num(row[key], f"{key}:{identity}")
    if value < 0.0 or value > 1.0:
        raise NflPropSimulationError(f"{key.upper()}_OUT_OF_RANGE:{identity}")
    return value


def _player_name(row: Mapping[str, Any]) -> str:
    name = str(row.get("player", "")).strip()
    if not name:
        raise NflPropSimulationError("PLAYER_IDENTITY_REQUIRED")
    return name


def _team_tds(state: Mapping[str, Any]) -> int:
    raw = state.get("team_tds")
    if isinstance(raw, bool):
        raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED") from exc
    if value < 0 or raw != value:
        raise NflPropSimulationError("TEAM_TDS_INTEGER_REQUIRED")
    return value


def _pass_td_share(state: Mapping[str, Any]) -> float:
    if "pass_td_share" not in state:
        raise NflPropSimulationError("PASS_TD_SHARE_REQUIRED")
    value = _num(state["pass_td_share"], "pass_td_share")
    if value < 0.0 or value > 1.0:
        raise NflPropSimulationError("PASS_TD_SHARE_OUT_OF_RANGE")
    return value


def _weighted_index(rng: random.Random, weights: Sequence[float], *, error: str) -> int:
    total = sum(max(0.0, float(weight)) for weight in weights)
    if total <= 0.0:
        raise NflPropSimulationError(error)
    cut = rng.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += max(0.0, float(weight))
        if cut < running:
            return index
    return len(weights) - 1


def _bounded_binomial(
    rng: random.Random,
    *,
    n: int,
    p: float,
    cap: int,
) -> int:
    """Draw Binomial(n,p) conditional on the physical capacity ``<= cap``.

    Conditioning, rather than clipping, preserves the fitted pass-TD share over
    the feasible support.  If the supplied share assigns zero probability to all
    feasible outcomes (for example p=1 with fewer completions than team TDs), the
    path fails closed instead of silently rewriting the share.
    """
    if n <= 0:
        return 0
    upper = min(n, max(0, int(cap)))
    weights: list[float] = []
    for k in range(upper + 1):
        if p == 0.0:
            weight = 1.0 if k == 0 else 0.0
        elif p == 1.0:
            weight = 1.0 if k == n else 0.0
        else:
            weight = comb(n, k) * (p**k) * ((1.0 - p) ** (n - k))
        weights.append(weight)
    total = sum(weights)
    if total <= 0.0:
        raise NflPropSimulationError("PASS_TD_CAPACITY_CONFLICT")
    cut = rng.random() * total
    running = 0.0
    for k, weight in enumerate(weights):
        running += weight
        if cut < running:
            return k
    return upper


def _allocate_passing_tds(
    rng: random.Random,
    passing_tds: int,
    names: Sequence[str],
    receiver_draws: Mapping[str, Mapping[str, Any]],
    shares: Mapping[str, float],
) -> dict[str, int]:
    allocated = {name: 0 for name in names}
    for _ in range(passing_tds):
        weights = []
        for name in names:
            receptions = int(receiver_draws[name]["receptions"])
            remaining_catches = max(0, receptions - allocated[name])
            weights.append(remaining_catches * shares[name])
        index = _weighted_index(
            rng,
            weights,
            error="PASSING_TD_RECEIVER_CAPACITY_REQUIRED",
        )
        allocated[names[index]] += 1
    return allocated


def _allocate_rushing_tds(
    rng: random.Random,
    rushing_tds: int,
    qb_name: str,
    qb_draw: Mapping[str, Any],
    qb_share: float,
    names: Sequence[str],
    player_draws: Mapping[str, Mapping[str, Any]],
    player_shares: Mapping[str, float],
) -> dict[str, int]:
    identities = [qb_name, *names]
    attempts = {
        qb_name: int(qb_draw["rush_attempts"]),
        **{name: int(player_draws[name]["rush_attempts"]) for name in names},
    }
    shares = {qb_name: qb_share, **player_shares}
    allocated = {name: 0 for name in identities}

    for _ in range(rushing_tds):
        weights = [
            max(0, attempts[name] - allocated[name]) * shares[name]
            for name in identities
        ]
        index = _weighted_index(
            rng,
            weights,
            error="RUSHING_TD_RUSHER_CAPACITY_REQUIRED",
        )
        allocated[identities[index]] += 1
    return allocated


def simulate_coherent_team_scoring_paths(
    qb_payload: Mapping[str, Any],
    skill_players: Sequence[Mapping[str, Any]],
    game_states: Sequence[Mapping[str, Any]],
    *,
    seed: int = 21,
) -> list[dict[str, Any]]:
    """Return one fully coherent QB/skill-player scoring draw per game path.

    One output path contains workload, receptions, passing/receiving/rushing
    yards, the team TD split, QB passing TDs, receiver passing TDs and rushing
    TDs.  Passing TD allocation uses only realized receptions; rushing TD
    allocation uses only realized carries.
    """
    if not skill_players:
        raise NflPropSimulationError("SKILL_PLAYERS_REQUIRED")
    if not game_states:
        raise NflPropSimulationError("GAME_STATES_REQUIRED")

    qb_name = _player_name(qb_payload)
    names = [_player_name(player) for player in skill_players]
    if qb_name in names or len(set(names)) != len(names):
        raise NflPropSimulationError("PLAYER_IDENTITY_DUPLICATE")

    receiver_shares = {
        name: _share(player, "receiving_td_share", name)
        for name, player in zip(names, skill_players)
    }
    rusher_shares = {
        name: _share(player, "rushing_td_share", name)
        for name, player in zip(names, skill_players)
    }
    qb_rushing_share = _share(qb_payload, "rushing_td_share", qb_name)

    # The existing function owns the same-path workload, completion and yardage
    # construction.  We consume those exact path draws rather than simulating a
    # second TD-only player universe.
    base_paths = simulate_team_on_game_paths(
        qb_payload,
        skill_players,
        game_states,
        seed=seed,
    )

    rng = random.Random(int(seed) ^ 0x5C0A1D7)
    out: list[dict[str, Any]] = []
    for state, path in zip(game_states, base_paths):
        team_tds = _team_tds(state)
        pass_share = _pass_td_share(state)
        qb_draw = dict(path["qb"])
        player_draws = {
            name: dict(path["receivers"][name])
            for name in names
        }

        passing_tds = _bounded_binomial(
            rng,
            n=team_tds,
            p=pass_share,
            cap=int(qb_draw["completions"]),
        )
        rushing_tds = team_tds - passing_tds

        receiving_tds = _allocate_passing_tds(
            rng,
            passing_tds,
            names,
            player_draws,
            receiver_shares,
        )
        rush_tds = _allocate_rushing_tds(
            rng,
            rushing_tds,
            qb_name,
            qb_draw,
            qb_rushing_share,
            names,
            player_draws,
            rusher_shares,
        )

        qb_draw["pass_tds"] = passing_tds
        qb_draw["rushing_tds"] = rush_tds[qb_name]
        qb_draw["anytime_tds"] = rush_tds[qb_name]

        for name in names:
            draw = player_draws[name]
            draw["receiving_tds"] = receiving_tds[name]
            draw["rushing_tds"] = rush_tds[name]
            draw["anytime_tds"] = receiving_tds[name] + rush_tds[name]

        # Runtime invariants: fail closed if a future edit breaks path identity.
        if passing_tds > int(qb_draw["completions"]):
            raise NflPropSimulationError("PASS_TDS_EXCEED_COMPLETIONS")
        if sum(receiving_tds.values()) != passing_tds:
            raise NflPropSimulationError("RECEIVER_TD_ALLOCATION_BROKEN")
        if any(receiving_tds[name] > int(player_draws[name]["receptions"]) for name in names):
            raise NflPropSimulationError("PASSING_TD_WITHOUT_RECEPTION")
        if rush_tds[qb_name] + sum(rush_tds[name] for name in names) != rushing_tds:
            raise NflPropSimulationError("RUSHING_TD_ALLOCATION_BROKEN")
        if passing_tds + rushing_tds != team_tds:
            raise NflPropSimulationError("TEAM_TD_SPLIT_BROKEN")
        if sum(player_draws[name]["receiving_yards"] for name in names) != qb_draw["passing_yards"]:
            raise NflPropSimulationError("PASSING_YARD_ALLOCATION_BROKEN")

        out.append(
            {
                "team": {
                    "team_tds": team_tds,
                    "passing_tds": passing_tds,
                    "rushing_tds": rushing_tds,
                },
                "qb": qb_draw,
                "players": player_draws,
            }
        )
    return out
