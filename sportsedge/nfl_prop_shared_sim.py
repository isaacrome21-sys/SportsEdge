"""Transparent NFL role/workload -> shared prop simulation.

Adapts disclosed MySpariEdge-style concepts (projected role, usage, matchup,
injury/context and shared simulation) without proprietary coefficients. Market
prices are forbidden here: this module produces independent estimate_p rows for
nfl_prop_run_it_score_b.

Same-game pairings must share one latent via simulate_game. Per-player
simulate_player is for isolated unit tests only; it is not a same-game board.
"""
from __future__ import annotations

from math import exp, isfinite, sqrt
import random
from typing import Any, Mapping, Sequence

PROP_STATS = frozenset({
    "receptions", "receiving_yards", "passing_yards", "rushing_yards",
    "rush_attempts", "pass_attempts", "completions", "pass_tds",
    "interceptions", "rush_receiving_yards",
})
ROLE_KEYS = (
    "pass_attempts", "completion_rate", "pass_yards_per_completion",
    "pass_td_rate", "interception_rate", "rush_attempts",
    "rush_yards_per_attempt", "targets", "catch_rate",
    "receiving_yards_per_reception",
)
RATE_KEYS = frozenset({"completion_rate", "pass_td_rate", "interception_rate", "catch_rate"})
TD_RATE_KEYS = frozenset({"pass_td_rate"})
# Volume stats keep a light 8-game prior; TD rates need much heavier regression.
DEFAULT_VOLUME_PRIOR_STRENGTH = 8.0
DEFAULT_TD_PRIOR_STRENGTH = 40.0
FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability",
    "implied_team_total", "implied_total", " vig", "no_vig",
})
FORBIDDEN_MARKET_KEY_FRAGMENTS = (
    "price", "odds", "american", "no_vig", "novig", "implied", "edge_", "ev_",
)


class NflPropSimulationError(ValueError):
    pass


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as e:
        raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED") from e
    if not isfinite(x):
        raise NflPropSimulationError(f"{name}:NONFINITE")
    return x


def _looks_like_market_key(key: str) -> bool:
    k = str(key).lower()
    if k in FORBIDDEN_MARKET_KEYS:
        return True
    return any(frag in k for frag in FORBIDDEN_MARKET_KEY_FRAGMENTS)


def _assert_no_market_inputs(node: Any, path: str = "") -> None:
    """Reject sportsbook / implied-price fields at any nesting depth."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = f"{path}.{key}" if path else str(key)
            if _looks_like_market_key(str(key)):
                raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
            _assert_no_market_inputs(value, name)
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _assert_no_market_inputs(value, f"{path}[{i}]")


def stabilized_role(
    payload: Mapping[str, Any],
    *,
    prior_strength: float = DEFAULT_VOLUME_PRIOR_STRENGTH,
    td_prior_strength: float = DEFAULT_TD_PRIOR_STRENGTH,
) -> dict[str, float]:
    _assert_no_market_inputs(payload)
    prior = payload.get("role_prior")
    trailing = payload.get("trailing") or {}
    if not isinstance(prior, Mapping):
        raise NflPropSimulationError("ROLE_PRIOR_REQUIRED")
    if not isinstance(trailing, Mapping):
        raise NflPropSimulationError("TRAILING_OBJECT_REQUIRED")
    n = max(0.0, _num(payload.get("sample_size", 0), "sample_size"))
    s_vol = _num(prior_strength, "prior_strength")
    s_td = _num(td_prior_strength, "td_prior_strength")
    if s_vol < 0 or s_td < 0 or n + s_vol <= 0:
        raise NflPropSimulationError("ROLE_WEIGHT_INVALID")
    out: dict[str, float] = {}
    for k in ROLE_KEYS:
        if k not in prior:
            raise NflPropSimulationError(f"ROLE_PRIOR_MISSING:{k}")
        p = _num(prior[k], k)
        o = p if k not in trailing else _num(trailing[k], k)
        s = s_td if k in TD_RATE_KEYS else s_vol
        v = (s * p + n * o) / (s + n)
        if v < 0 or (k in RATE_KEYS and v > 1):
            raise NflPropSimulationError(f"ROLE_VALUE_INVALID:{k}")
        out[k] = v
    return out


def _ctx(payload: Mapping[str, Any], key: str, default: float = 1.0) -> float:
    c = payload.get("context") or {}
    if not isinstance(c, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    v = _num(c.get(key, default), f"context.{key}")
    if v <= 0:
        raise NflPropSimulationError(f"CONTEXT_POSITIVE_REQUIRED:{key}")
    return v


def _poisson(rng: random.Random, mu: float) -> int:
    if mu <= 0:
        return 0
    if mu > 60:
        return max(0, int(round(rng.gauss(mu, sqrt(mu)))))
    lim = exp(-mu)
    p = 1.0
    k = 0
    while p > lim:
        k += 1
        p *= rng.random()
    return k - 1


def _binom(rng: random.Random, n: int, p: float) -> int:
    p = min(1.0, max(0.0, p))
    return sum(rng.random() < p for _ in range(max(0, n)))


def _receiving_yards(rng: random.Random, n: int, mean: float) -> int:
    if mean <= 0 or n <= 0:
        return 0
    return max(0, int(round(sum(rng.gammavariate(2.0, mean / 2.0) for _ in range(n)))))


def _rushing_yards(rng: random.Random, n: int, mean: float) -> int:
    """Per-carry Gaussian so stuffed / lost-yardage carries can go negative."""
    if n <= 0:
        return 0
    sd = max(2.5, abs(mean) * 0.85)
    total = sum(rng.gauss(mean, sd) for _ in range(n))
    return int(round(total))


def _passing_yards(rng: random.Random, n: int, mean: float) -> int:
    if mean <= 0 or n <= 0:
        return 0
    return max(0, int(round(sum(rng.gammavariate(2.0, mean / 2.0) for _ in range(n)))))


def _one_draw(role: Mapping[str, float], payload: Mapping[str, Any], rng: random.Random, latent: float) -> dict[str, int]:
    vol = _ctx(payload, "volume_multiplier")
    pm = _ctx(payload, "pass_multiplier")
    rm = _ctx(payload, "rush_multiplier")
    tm = _ctx(payload, "target_multiplier")
    eff = _ctx(payload, "efficiency_multiplier")
    pe = _ctx(payload, "pass_efficiency_multiplier")
    re = _ctx(payload, "rush_efficiency_multiplier")
    ce = _ctx(payload, "receiving_efficiency_multiplier")
    pa = _poisson(rng, role["pass_attempts"] * vol * pm * latent)
    ra = _poisson(rng, role["rush_attempts"] * vol * rm * latent)
    tg = _poisson(rng, role["targets"] * vol * tm * latent)
    comp = _binom(rng, pa, role["completion_rate"])
    rec = _binom(rng, tg, role["catch_rate"])
    py = _passing_yards(rng, comp, role["pass_yards_per_completion"] * eff * pe)
    ry = _rushing_yards(rng, ra, role["rush_yards_per_attempt"] * eff * re)
    cy = _receiving_yards(rng, rec, role["receiving_yards_per_reception"] * eff * ce)
    # TDs are a subset of completions so they cannot exceed completions.
    cr = max(role["completion_rate"], 1e-6)
    td_given_comp = min(1.0, role["pass_td_rate"] / cr)
    pass_tds = _binom(rng, comp, td_given_comp)
    ints = _binom(rng, max(0, pa - pass_tds), role["interception_rate"])
    return {
        "pass_attempts": pa,
        "completions": comp,
        "passing_yards": py,
        "pass_tds": pass_tds,
        "interceptions": ints,
        "rush_attempts": ra,
        "rushing_yards": ry,
        "receptions": rec,
        "receiving_yards": cy,
        "rush_receiving_yards": ry + cy,
    }


def _latent(rng: random.Random, sigma: float) -> float:
    if sigma == 0:
        return 1.0
    return rng.lognormvariate(-0.5 * sigma * sigma, sigma)


def _sigma(payload: Mapping[str, Any]) -> float:
    c = payload.get("context") or {}
    if not isinstance(c, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    sigma = _num(c.get("shared_workload_sigma", 0.12), "context.shared_workload_sigma")
    if sigma < 0:
        raise NflPropSimulationError("SHARED_SIGMA_INVALID")
    return sigma


def simulate_player(
    payload: Mapping[str, Any],
    *,
    n_sims: int = 20000,
    seed: int = 21,
) -> list[dict[str, int]]:
    """Isolated player draws. Same-game boards must use simulate_game."""
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NflPropSimulationError("N_SIMS_INVALID")
    _assert_no_market_inputs(payload)
    role = stabilized_role(payload)
    rng = random.Random(int(seed))
    sigma = _sigma(payload)
    out = []
    for _ in range(int(n_sims)):
        out.append(_one_draw(role, payload, rng, _latent(rng, sigma)))
    return out


def simulate_game(
    players: Sequence[Mapping[str, Any]],
    *,
    n_sims: int = 20000,
    seed: int = 21,
) -> list[list[dict[str, int]]]:
    """Same-game simulation: one shared latent per draw across all players.

    Returns n_sims lists, each list aligned to `players`.
    This is the hook for #1006 / #1007 coherent game-script pairing.
    """
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NflPropSimulationError("N_SIMS_INVALID")
    if not players:
        raise NflPropSimulationError("PLAYERS_REQUIRED")
    for payload in players:
        _assert_no_market_inputs(payload)
    roles = [stabilized_role(p) for p in players]
    rng = random.Random(int(seed))
    # Game-level sigma is the max of player sigmas so a quiet player cannot mute the script.
    sigma = max(_sigma(p) for p in players)
    games: list[list[dict[str, int]]] = []
    for _ in range(int(n_sims)):
        latent = _latent(rng, sigma)
        games.append([_one_draw(role, payload, rng, latent) for role, payload in zip(roles, players)])
    return games


def estimate_prop(
    draws: Sequence[Mapping[str, Any]],
    *,
    game_id: str,
    player: str,
    market: str,
    line: float,
    selection: str,
) -> dict[str, Any]:
    if market not in PROP_STATS or selection.upper() not in {"OVER", "UNDER"} or not draws:
        raise NflPropSimulationError("PROP_IDENTITY_INVALID")
    threshold = _num(line, "line")
    over = under = push = 0
    for d in draws:
        v = _num(d.get(market), market)
        if v > threshold:
            over += 1
        elif v < threshold:
            under += 1
        else:
            push += 1
    n = float(len(draws))
    side = selection.upper()
    return {
        "game_id": str(game_id),
        "player": str(player),
        "market": market,
        "selection": side,
        "line": threshold,
        "estimate_p": (over if side == "OVER" else under) / n,
        "push_p": push / n,
    }
