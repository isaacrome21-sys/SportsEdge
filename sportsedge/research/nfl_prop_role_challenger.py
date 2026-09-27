"""Research-only NFL player-prop role challenger.

This module adapts a transparent role -> workload -> shared simulation -> price
workflow for SportsEdge.  It does not contain proprietary third-party coefficients
and it cannot grant Model_P, Truth Gate, staking, promotion, or OFFICIAL authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp, isfinite, log, sqrt
import random
from typing import Any, Iterable, Mapping, Sequence


VERSION = "nfl_prop_role_challenger_v1_research"
AUTHORITY_FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
QUOTE_TTL_SECONDS = 180
MAX_QUOTE_SKEW_SECONDS = 30
DEVIG_METHOD = "POWER_V1"
REQUIRED_BOOK = "DraftKings"
LONGSHOT_SENSITIVITY_TRIGGER = 400
MAX_DEVIG_SENSITIVITY_PP = 1.0

PROP_FAMILIES = (
    "receptions",
    "receiving_yards",
    "passing_yards",
    "rushing_yards",
    "rush_attempts",
    "pass_attempts",
    "completions",
    "pass_tds",
    "interceptions",
    "rush_receiving_yards",
)

ROLE_METRICS = (
    "pass_attempts",
    "completion_rate",
    "pass_yards_per_completion",
    "pass_td_rate",
    "interception_rate",
    "rush_attempts",
    "rush_yards_per_attempt",
    "targets",
    "catch_rate",
    "receiving_yards_per_reception",
)
RATE_METRICS = {"completion_rate", "pass_td_rate", "interception_rate", "catch_rate"}


class NFLPropResearchError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise NFLPropResearchError(f"{field}:NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLPropResearchError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(x):
        raise NFLPropResearchError(f"{field}:NONFINITE")
    return x


def _nonnegative(value: Any, field: str) -> float:
    x = _finite(value, field)
    if x < 0:
        raise NFLPropResearchError(f"{field}:NEGATIVE")
    return x


def _rate(value: Any, field: str) -> float:
    x = _finite(value, field)
    if not 0.0 <= x <= 1.0:
        raise NFLPropResearchError(f"{field}:RATE_OUT_OF_RANGE")
    return x


def stabilize_role_metric(
    prior: Any,
    observed: Any | None,
    sample_size: Any,
    *,
    prior_strength: Any = 8.0,
) -> float:
    """Shrink trailing usage/efficiency toward a projected-role prior.

    No hidden/fitted weights are used: the prior-equivalent sample strength is an
    explicit argument and therefore auditable in every research run.
    """
    p = _finite(prior, "prior")
    if observed is None:
        return p
    o = _finite(observed, "observed")
    n = _nonnegative(sample_size, "sample_size")
    strength = _nonnegative(prior_strength, "prior_strength")
    denom = n + strength
    if denom <= 0:
        raise NFLPropResearchError("ROLE_WEIGHT_ZERO")
    return (strength * p + n * o) / denom


def stabilized_role(payload: Mapping[str, Any], *, prior_strength: float = 8.0) -> dict[str, float]:
    prior = payload.get("role_prior")
    if not isinstance(prior, Mapping):
        raise NFLPropResearchError("ROLE_PRIOR_REQUIRED")
    observed = payload.get("trailing", {})
    if observed is None:
        observed = {}
    if not isinstance(observed, Mapping):
        raise NFLPropResearchError("TRAILING_OBJECT_REQUIRED")
    sample_size = payload.get("sample_size", 0)
    role: dict[str, float] = {}
    for metric in ROLE_METRICS:
        if metric not in prior:
            raise NFLPropResearchError(f"ROLE_PRIOR_MISSING:{metric}")
        value = stabilize_role_metric(
            prior[metric], observed.get(metric), sample_size, prior_strength=prior_strength
        )
        role[metric] = _rate(value, metric) if metric in RATE_METRICS else _nonnegative(value, metric)
    return role


def _context(payload: Mapping[str, Any], key: str, default: float = 1.0) -> float:
    raw = payload.get("context", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise NFLPropResearchError("CONTEXT_OBJECT_REQUIRED")
    value = _finite(raw.get(key, default), f"context.{key}")
    if value <= 0:
        raise NFLPropResearchError(f"context.{key}:POSITIVE_REQUIRED")
    return value


def _binomial(rng: random.Random, n: int, p: float) -> int:
    if n <= 0 or p <= 0:
        return 0
    if p >= 1:
        return n
    return sum(1 for _ in range(n) if rng.random() < p)


def _poisson(rng: random.Random, mu: float) -> int:
    if mu <= 0:
        return 0
    # Exact Knuth sampling in the ordinary NFL workload range; use a normal
    # approximation only for unusually large research inputs.
    if mu > 60:
        return max(0, int(round(rng.gauss(mu, sqrt(mu)))))
    limit = exp(-mu)
    k = 0
    product = 1.0
    while product > limit:
        k += 1
        product *= rng.random()
    return k - 1


def _positive_yards(rng: random.Random, opportunities: int, mean_per_opportunity: float) -> int:
    if opportunities <= 0 or mean_per_opportunity <= 0:
        return 0
    # Gamma per opportunity keeps yards nonnegative and right-skewed.  Shape=2
    # is an explicit research assumption, not a fitted or third-party parameter.
    total = sum(rng.gammavariate(2.0, mean_per_opportunity / 2.0) for _ in range(opportunities))
    return max(0, int(round(total)))


def simulate_player_role(
    payload: Mapping[str, Any],
    *,
    n_sims: int = 20_000,
    seed: int = 21,
    prior_strength: float = 8.0,
) -> list[dict[str, int]]:
    """Generate coherent per-draw player statistics from one shared workload."""
    if isinstance(n_sims, bool) or int(n_sims) != n_sims or n_sims <= 0:
        raise NFLPropResearchError("N_SIMS_POSITIVE_INTEGER_REQUIRED")
    role = stabilized_role(payload, prior_strength=prior_strength)
    rng = random.Random(int(seed))

    volume_mult = _context(payload, "volume_multiplier")
    pass_mult = _context(payload, "pass_multiplier")
    rush_mult = _context(payload, "rush_multiplier")
    target_mult = _context(payload, "target_multiplier")
    efficiency_mult = _context(payload, "efficiency_multiplier")
    pass_eff_mult = _context(payload, "pass_efficiency_multiplier")
    rush_eff_mult = _context(payload, "rush_efficiency_multiplier")
    receive_eff_mult = _context(payload, "receiving_efficiency_multiplier")
    raw_context = payload.get("context") or {}
    shared_sigma = _nonnegative(raw_context.get("shared_workload_sigma", 0.12), "context.shared_workload_sigma")

    draws: list[dict[str, int]] = []
    for _ in range(int(n_sims)):
        latent = 1.0 if shared_sigma == 0 else rng.lognormvariate(-0.5 * shared_sigma * shared_sigma, shared_sigma)
        pass_attempts = _poisson(rng, role["pass_attempts"] * volume_mult * pass_mult * latent)
        rush_attempts = _poisson(rng, role["rush_attempts"] * volume_mult * rush_mult * latent)
        targets = _poisson(rng, role["targets"] * volume_mult * target_mult * latent)

        completions = _binomial(rng, pass_attempts, role["completion_rate"])
        receptions = _binomial(rng, targets, role["catch_rate"])
        passing_yards = _positive_yards(
            rng,
            completions,
            role["pass_yards_per_completion"] * efficiency_mult * pass_eff_mult,
        )
        rushing_yards = _positive_yards(
            rng,
            rush_attempts,
            role["rush_yards_per_attempt"] * efficiency_mult * rush_eff_mult,
        )
        receiving_yards = _positive_yards(
            rng,
            receptions,
            role["receiving_yards_per_reception"] * efficiency_mult * receive_eff_mult,
        )
        pass_tds = _binomial(rng, pass_attempts, role["pass_td_rate"])
        interceptions = _binomial(rng, pass_attempts, role["interception_rate"])

        draws.append(
            {
                "pass_attempts": pass_attempts,
                "completions": completions,
                "passing_yards": passing_yards,
                "pass_tds": pass_tds,
                "interceptions": interceptions,
                "rush_attempts": rush_attempts,
                "rushing_yards": rushing_yards,
                "targets": targets,
                "receptions": receptions,
                "receiving_yards": receiving_yards,
                "rush_receiving_yards": rushing_yards + receiving_yards,
            }
        )
    return draws


def price_simulated_prop(draws: Sequence[Mapping[str, Any]], *, market: str, line: Any) -> dict[str, float]:
    if market not in PROP_FAMILIES:
        raise NFLPropResearchError(f"UNSUPPORTED_PROP:{market}")
    threshold = _nonnegative(line, "line")
    if not draws:
        raise NFLPropResearchError("SIMULATIONS_REQUIRED")
    over = under = push = 0
    for draw in draws:
        if market not in draw:
            raise NFLPropResearchError(f"SIMULATION_STAT_MISSING:{market}")
        value = _finite(draw[market], market)
        if value > threshold:
            over += 1
        elif value < threshold:
            under += 1
        else:
            push += 1
    n = float(len(draws))
    result = {
        "over": over / n,
        "under": under / n,
        "push": push / n,
    }
    if abs(sum(result.values()) - 1.0) > 1e-12:
        raise NFLPropResearchError("PROP_PROBABILITY_MASS_INVALID")
    return result


def _american_to_decimal(odds: Any) -> float:
    if isinstance(odds, bool):
        raise NFLPropResearchError("AMERICAN_ODDS_INTEGER_REQUIRED")
    try:
        a = int(odds)
    except (TypeError, ValueError) as exc:
        raise NFLPropResearchError("AMERICAN_ODDS_INTEGER_REQUIRED") from exc
    if str(a) != str(odds).strip() and not isinstance(odds, int):
        try:
            if float(odds) != a:
                raise NFLPropResearchError("AMERICAN_ODDS_INTEGER_REQUIRED")
        except (TypeError, ValueError) as exc:
            raise NFLPropResearchError("AMERICAN_ODDS_INTEGER_REQUIRED") from exc
    if -100 < a < 100:
        raise NFLPropResearchError("AMERICAN_ODDS_OUT_OF_RANGE")
    return 1.0 + (100.0 / abs(a) if a < 0 else a / 100.0)


def _implied_probability(odds: Any) -> float:
    return 1.0 / _american_to_decimal(odds)


def _power_devig(q1: float, q2: float) -> tuple[float, float]:
    if q1 <= 0 or q2 <= 0:
        raise NFLPropResearchError("DEVIG_INVALID_IMPLIED_PROBABILITY")
    lo, hi = 0.01, 20.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        mass = q1**mid + q2**mid
        if mass > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    p1, p2 = q1**k, q2**k
    total = p1 + p2
    return p1 / total, p2 / total


def _devig_pair(over_odds: Any, under_odds: Any) -> tuple[float, float, float]:
    q_over = _implied_probability(over_odds)
    q_under = _implied_probability(under_odds)
    p_over, p_under = _power_devig(q_over, q_under)
    sensitivity_pp = 0.0
    a_over, a_under = int(over_odds), int(under_odds)
    if max(a_over, a_under) > LONGSHOT_SENSITIVITY_TRIGGER:
        prop_over = q_over / (q_over + q_under)
        prop_under = 1.0 - prop_over
        overround = q_over + q_under - 1.0
        add_over = q_over - overround / 2.0
        add_under = q_under - overround / 2.0
        if add_over > 0 and add_under > 0:
            add_total = add_over + add_under
            add_over /= add_total
            add_under /= add_total
        else:
            add_over, add_under = prop_over, prop_under
        sensitivity_pp = 100.0 * max(
            abs(p_over - prop_over),
            abs(p_under - prop_under),
            abs(p_over - add_over),
            abs(p_under - add_under),
        )
        if sensitivity_pp > MAX_DEVIG_SENSITIVITY_PP:
            raise NFLPropResearchError(f"DEVIG_METHOD_SENSITIVITY:{sensitivity_pp:.6f}pp")
    return p_over, p_under, sensitivity_pp


def _parse_time(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NFLPropResearchError(f"{field}:INVALID_TIMESTAMP") from exc
    else:
        raise NFLPropResearchError(f"{field}:TIMESTAMP_REQUIRED")
    if dt.tzinfo is None:
        raise NFLPropResearchError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _normalize_pair(
    quotes: Iterable[Mapping[str, Any]],
    *,
    player_id: str,
    market: str,
    line: float,
    as_of: Any,
) -> dict[str, dict[str, Any]]:
    now = _parse_time(as_of, "as_of")
    pair: dict[str, dict[str, Any]] = {}
    for raw in quotes:
        if str(raw.get("player_id", "")) != str(player_id):
            continue
        if raw.get("market") != market:
            continue
        if _finite(raw.get("line"), "quote.line") != line:
            continue
        if raw.get("book") != REQUIRED_BOOK:
            raise NFLPropResearchError("BOOK_NOT_ALLOWED")
        side = str(raw.get("side", "")).upper()
        if side not in {"OVER", "UNDER"}:
            raise NFLPropResearchError("QUOTE_SIDE_INVALID")
        if side in pair:
            raise NFLPropResearchError(f"DUPLICATE_QUOTE_SIDE:{side}")
        retrieved = _parse_time(raw.get("retrieved_at"), "retrieved_at")
        age = (now - retrieved).total_seconds()
        if age > QUOTE_TTL_SECONDS:
            raise NFLPropResearchError("QUOTE_STALE")
        if age < -MAX_QUOTE_SKEW_SECONDS:
            raise NFLPropResearchError("QUOTE_CLOCK_SKEW")
        _american_to_decimal(raw.get("price_american"))
        pair[side] = {
            "price_american": int(raw["price_american"]),
            "retrieved_at": retrieved,
            "book": REQUIRED_BOOK,
        }
    if set(pair) != {"OVER", "UNDER"}:
        raise NFLPropResearchError("PAIRED_QUOTES_REQUIRED")
    skew = abs((pair["OVER"]["retrieved_at"] - pair["UNDER"]["retrieved_at"]).total_seconds())
    if skew > MAX_QUOTE_SKEW_SECONDS:
        raise NFLPropResearchError("PAIRED_QUOTE_TIME_SKEW")
    return pair


def _fair_american(win_p: float, push_p: float) -> int | None:
    if win_p <= 0:
        return None
    fair_decimal = (1.0 - push_p) / win_p
    if fair_decimal <= 1.0:
        return -1000000
    if fair_decimal >= 2.0:
        return int(round((fair_decimal - 1.0) * 100.0))
    return int(round(-100.0 / (fair_decimal - 1.0)))


def evaluate_prop_market(
    draws: Sequence[Mapping[str, Any]],
    *,
    player_id: str,
    player_name: str,
    game_id: str,
    market: str,
    line: Any,
    quotes: Iterable[Mapping[str, Any]],
    as_of: Any,
) -> list[dict[str, Any]]:
    threshold = _nonnegative(line, "line")
    probabilities = price_simulated_prop(draws, market=market, line=threshold)
    pair = _normalize_pair(
        quotes,
        player_id=player_id,
        market=market,
        line=threshold,
        as_of=as_of,
    )
    market_over, market_under, sensitivity_pp = _devig_pair(
        pair["OVER"]["price_american"], pair["UNDER"]["price_american"]
    )
    push_p = probabilities["push"]
    nonpush = 1.0 - push_p
    if nonpush <= 0:
        raise NFLPropResearchError("ALL_SIMULATIONS_PUSH")

    rows: list[dict[str, Any]] = []
    for side, key, market_p in (
        ("OVER", "over", market_over),
        ("UNDER", "under", market_under),
    ):
        estimate_p = probabilities[key]
        conditional_p = estimate_p / nonpush
        decimal_odds = _american_to_decimal(pair[side]["price_american"])
        loss_p = 1.0 - estimate_p - push_p
        ev = estimate_p * (decimal_odds - 1.0) - loss_p
        rows.append(
            {
                "version": VERSION,
                "game_id": str(game_id),
                "player_id": str(player_id),
                "player_name": str(player_name),
                "market": market,
                "side": side,
                "line": threshold,
                "price_american": pair[side]["price_american"],
                "book": REQUIRED_BOOK,
                "retrieved_at": pair[side]["retrieved_at"].isoformat(),
                "estimate_p": estimate_p,
                "push_p": push_p,
                "conditional_nonpush_estimate_p": conditional_p,
                "market_no_vig_p": market_p,
                "edge_probability_points": 100.0 * (conditional_p - market_p),
                "ev_per_dollar": ev,
                "fair_american": _fair_american(estimate_p, push_p),
                "devig_method": DEVIG_METHOD,
                "devig_sensitivity_pp": sensitivity_pp,
                "authority": AUTHORITY_FOOTER,
            }
        )
    return rows


def rank_prop_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    materialized = [dict(row) for row in rows]
    materialized.sort(
        key=lambda row: (
            -_finite(row.get("ev_per_dollar"), "ev_per_dollar"),
            -_finite(row.get("edge_probability_points"), "edge_probability_points"),
            str(row.get("game_id", "")),
            str(row.get("player_id", "")),
            str(row.get("market", "")),
            str(row.get("side", "")),
        )
    )
    for rank, row in enumerate(materialized, start=1):
        row["rank"] = rank
    return materialized


def build_prop_card(
    players: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    *,
    as_of: Any,
    n_sims: int = 20_000,
    seed: int = 21,
    prior_strength: float = 8.0,
) -> dict[str, Any]:
    """Build a non-authoritative card and preserve refusals as dispositions."""
    rows: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    for player_index, player in enumerate(players):
        player_id = str(player.get("player_id", ""))
        if not player_id:
            raise NFLPropResearchError("PLAYER_ID_REQUIRED")
        draws = simulate_player_role(
            player,
            n_sims=n_sims,
            seed=int(seed) + player_index,
            prior_strength=prior_strength,
        )
        groups: dict[tuple[str, float], list[Mapping[str, Any]]] = {}
        for quote in quotes:
            if str(quote.get("player_id", "")) != player_id:
                continue
            market = str(quote.get("market", ""))
            if market not in PROP_FAMILIES:
                dispositions.append({"player_id": player_id, "market": market, "reason": "UNSUPPORTED_PROP"})
                continue
            line = _nonnegative(quote.get("line"), "quote.line")
            groups.setdefault((market, line), []).append(quote)
        for (market, line), group in sorted(groups.items()):
            try:
                rows.extend(
                    evaluate_prop_market(
                        draws,
                        player_id=player_id,
                        player_name=str(player.get("player_name", player_id)),
                        game_id=str(player.get("game_id", "")),
                        market=market,
                        line=line,
                        quotes=group,
                        as_of=as_of,
                    )
                )
            except NFLPropResearchError as exc:
                dispositions.append(
                    {"player_id": player_id, "market": market, "line": line, "reason": str(exc)}
                )
    return {
        "version": VERSION,
        "as_of": _parse_time(as_of, "as_of").isoformat(),
        "candidates": rank_prop_candidates(rows),
        "dispositions": dispositions,
        "authority": AUTHORITY_FOOTER,
    }
