"""Transparent NFL role/workload -> independent prop simulation.

Adapts disclosed MySpariEdge-style concepts (projected role, usage, matchup,
injury/context) without proprietary coefficients. Market prices are forbidden
here: this module produces independent estimate_p rows for nfl_prop_run_it_score_b.

simulate_game is a placeholder shared-volume latent only. It does not allocate
QB passing yards onto receivers and does not invert pass vs rush by game script.
Coherent same-game pairing belongs in the #1006 / #1007 collapse.
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
RARE_RATE_KEYS = frozenset({"pass_td_rate", "interception_rate"})
DEFAULT_VOLUME_PRIOR_STRENGTH = 8.0
DEFAULT_RARE_PRIOR_STRENGTH = 40.0

# Context multipliers are bounded, market-blind nudges only. They are not a
# transport for genuine role changes. A backup moving from (say) 6 to 18
# expected carries belongs in role_prior, with provenance, rather than a 3x
# multiplier. Do not widen this bound to encode a new role.
MULTIPLIER_KEYS = (
    "volume_multiplier", "pass_multiplier", "rush_multiplier", "target_multiplier",
    "efficiency_multiplier", "pass_efficiency_multiplier",
    "rush_efficiency_multiplier", "receiving_efficiency_multiplier",
)
MULTIPLIER_MIN = 0.40
MULTIPLIER_MAX = 1.80
ALLOWED_CONTEXT_SOURCES = frozenset({
    "role", "injury", "weather", "matchup", "participation", "none",
})

# Rushing-carry mixture. The tail is 12 + Gamma(2, 4.5), so its mean is known
# exactly (21.0). Solving the bulk mean from the mixture identity preserves the
# caller's requested yards/carry for every input mean, including stuffed backs.
RUSH_EXPLOSIVE_PROB = 0.06
RUSH_EXPLOSIVE_FLOOR = 12.0
RUSH_EXPLOSIVE_GAMMA_SHAPE = 2.0
RUSH_EXPLOSIVE_GAMMA_SCALE = 4.5
RUSH_EXPLOSIVE_MEAN = (
    RUSH_EXPLOSIVE_FLOOR
    + RUSH_EXPLOSIVE_GAMMA_SHAPE * RUSH_EXPLOSIVE_GAMMA_SCALE
)

FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability",
    "implied_team_total", "implied_total", "no_vig", "novig",
    "american_odds", "price", "vig",
})
# Exact-ish fragments only. Do not use "ev_" — it flags prev_week_targets.
FORBIDDEN_MARKET_KEY_FRAGMENTS = (
    "price_american", "american_odds", "no_vig", "novig", "implied_team",
    "implied_total", "sportsbook", "fair_american", "ev_per", "edge_probability",
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
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = f"{path}.{key}" if path else str(key)
            if _looks_like_market_key(str(key)):
                raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
            _assert_no_market_inputs(value, name)
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _assert_no_market_inputs(value, f"{path}[{i}]")


def _assert_market_blind_context(payload: Mapping[str, Any]) -> None:
    c = payload.get("context") or {}
    if not isinstance(c, Mapping):
        raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")

    source_raw = c.get("source", payload.get("context_source"))
    source = "none" if source_raw is None else str(source_raw).lower()
    if source not in ALLOWED_CONTEXT_SOURCES:
        raise NflPropSimulationError("CONTEXT_SOURCE_NOT_MARKET_BLIND")

    adjusted = False
    for key in MULTIPLIER_KEYS:
        if key not in c:
            continue
        v = _num(c[key], f"context.{key}")
        if v < MULTIPLIER_MIN or v > MULTIPLIER_MAX:
            raise NflPropSimulationError(f"CONTEXT_MULTIPLIER_OUT_OF_RANGE:{key}")
        if abs(v - 1.0) > 1e-12:
            adjusted = True

    # An actual adjustment must identify its market-blind evidence source.
    # `none` is reserved for an unadjusted context, not as a provenance bypass.
    if adjusted and (source_raw is None or source == "none"):
        raise NflPropSimulationError("CONTEXT_SOURCE_REQUIRED")


def stabilized_role(
    payload: Mapping[str, Any],
    *,
    prior_strength: float = DEFAULT_VOLUME_PRIOR_STRENGTH,
    rare_prior_strength: float = DEFAULT_RARE_PRIOR_STRENGTH,
    td_prior_strength: float | None = None,
) -> dict[str, float]:
    _assert_no_market_inputs(payload)
    _assert_market_blind_context(payload)
    prior = payload.get("role_prior")
    trailing = payload.get("trailing") or {}
    if not isinstance(prior, Mapping):
        raise NflPropSimulationError("ROLE_PRIOR_REQUIRED")
    if not isinstance(trailing, Mapping):
        raise NflPropSimulationError("TRAILING_OBJECT_REQUIRED")
    n = max(0.0, _num(payload.get("sample_size", 0), "sample_size"))
    s_vol = _num(prior_strength, "prior_strength")
    s_rare = _num(
        rare_prior_strength if td_prior_strength is None else td_prior_strength,
        "rare_prior_strength",
    )
    if s_vol < 0 or s_rare < 0 or n + s_vol <= 0:
        raise NflPropSimulationError("ROLE_WEIGHT_INVALID")
    out: dict[str, float] = {}
    for k in ROLE_KEYS:
        if k not in prior:
            raise NflPropSimulationError(f"ROLE_PRIOR_MISSING:{k}")
        p = _num(prior[k], k)
        o = p if k not in trailing else _num(trailing[k], k)
        s = s_rare if k in RARE_RATE_KEYS else s_vol
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
    if key in MULTIPLIER_KEYS and (v < MULTIPLIER_MIN or v > MULTIPLIER_MAX):
        raise NflPropSimulationError(f"CONTEXT_MULTIPLIER_OUT_OF_RANGE:{key}")
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


def _rush_carry(rng: random.Random, mean: float) -> float:
    """Gaussian bulk plus explosive tail with exactly preserved E[yards/carry]."""
    bulk_mean = (
        mean - RUSH_EXPLOSIVE_PROB * RUSH_EXPLOSIVE_MEAN
    ) / (1.0 - RUSH_EXPLOSIVE_PROB)
    if rng.random() < RUSH_EXPLOSIVE_PROB:
        return RUSH_EXPLOSIVE_FLOOR + rng.gammavariate(
            RUSH_EXPLOSIVE_GAMMA_SHAPE,
            RUSH_EXPLOSIVE_GAMMA_SCALE,
        )
    sd = max(2.2, abs(mean) * 0.70)
    return rng.gauss(bulk_mean, sd)


def _rushing_yards(rng: random.Random, n: int, mean: float) -> int:
    if n <= 0:
        return 0
    return int(round(sum(_rush_carry(rng, mean) for _ in range(n))))


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
    cr = max(role["completion_rate"], 1e-6)
    inc_rate = max(1.0 - role["completion_rate"], 1e-6)
    td_given_comp = min(1.0, role["pass_td_rate"] / cr)
    int_given_inc = min(1.0, role["interception_rate"] / inc_rate)
    pass_tds = _binom(rng, comp, td_given_comp)
    incompletions = max(0, pa - comp)
    ints = _binom(rng, incompletions, int_given_inc)
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
    """Isolated player draws. Not a same-game board."""
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NflPropSimulationError("N_SIMS_INVALID")
    _assert_no_market_inputs(payload)
    _assert_market_blind_context(payload)
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
    """Placeholder: one shared volume latent per draw.

    Does not conserve passing yards across QB and receivers, and does not
    invert pass vs rush when a team trails. Use the #1006/#1007 stack for that.
    """
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NflPropSimulationError("N_SIMS_INVALID")
    if not players:
        raise NflPropSimulationError("PLAYERS_REQUIRED")
    for payload in players:
        _assert_no_market_inputs(payload)
        _assert_market_blind_context(payload)
    roles = [stabilized_role(p) for p in players]
    rng = random.Random(int(seed))
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
