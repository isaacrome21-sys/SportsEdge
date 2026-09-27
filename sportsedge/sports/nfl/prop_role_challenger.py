"""Role-based NFL player-prop challenger.

Research only. This module may emit ``estimate_p`` values for chronological
validation, but it grants no Model_P, Truth Gate, promotion, staking, or
OFFICIAL authority.

Design:
  role/usage -> context -> shared player simulation -> prop distribution
  -> paired market quote -> POWER_V1 no-vig + EV

The predictive lane is market-blind. Sportsbook line/price, market depth, and
book agreement are accepted only by the post-model quote/diagnostic layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, isfinite
import random
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, american_to_decimal, devig

STATUS = "RESEARCH_ONLY_NO_MODEL_P"
AUTHORITY_FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"
MODEL_ID = "NFL_ROLE_PROP_CHALLENGER_V1"
QUOTE_TTL_SECONDS = 180
MAX_QUOTE_SKEW_SECONDS = 30

SUPPORTED_MARKETS = {
    "PASS_ATTEMPTS": "pass_attempts",
    "COMPLETIONS": "completions",
    "PASSING_YARDS": "passing_yards",
    "PASSING_TDS": "passing_tds",
    "INTERCEPTIONS": "interceptions",
    "RUSH_ATTEMPTS": "rush_attempts",
    "RUSHING_YARDS": "rushing_yards",
    "RECEPTIONS": "receptions",
    "RECEIVING_YARDS": "receiving_yards",
    "RUSH_RECEIVING_YARDS": "rush_receiving_yards",
}

_MARKET_KEYS = {
    "odds", "price", "line", "spread", "total", "sportsbook", "book",
    "market", "american_odds", "decimal_odds", "implied_probability",
    "no_vig_probability", "closing_line", "opening_line", "prop_line",
    "over_price", "under_price", "market_depth", "book_count",
}


class PropChallengerError(ValueError):
    pass


def _reject_market_inputs(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _MARKET_KEYS or "sportsbook" in normalized or "market_price" in normalized:
                raise PropChallengerError(f"MARKET_INPUT_FORBIDDEN:{key}")
            _reject_market_inputs(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_market_inputs(child)


def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PropChallengerError(f"BAD_NUMERIC:{name}") from exc
    if not isfinite(out):
        raise PropChallengerError(f"BAD_NUMERIC:{name}")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise PropChallengerError(f"PROBABILITY_OUT_OF_RANGE:{name}")
    return out


def _weighted_mean(values: Sequence[float], decay: float) -> tuple[float, float]:
    if not values:
        raise PropChallengerError("NO_VALUES")
    n = len(values)
    weights = [decay ** (n - 1 - i) for i in range(n)]
    sw = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / sw, sw


@dataclass(frozen=True)
class RoleProjection:
    entity_id: str
    pass_attempt_mean: float
    rush_attempt_mean: float
    target_mean: float
    availability_probability: float
    history_games: int
    source: str
    model_id: str = MODEL_ID
    status: str = STATUS


def stabilize_role(
    *,
    entity_id: str,
    history: Sequence[Mapping[str, Any]],
    projected_role: Mapping[str, Any],
    availability_probability: float = 1.0,
    decay: float = 0.82,
    shrink_games: float = 4.0,
    min_history_games: int = 3,
) -> RoleProjection:
    """Shrink trailing player usage toward a pregame projected-role prior.

    ``projected_role`` contains market-blind means for pass attempts, rush
    attempts, and targets. Sparse/new-role players fail over to that prior
    instead of treating a tiny trailing sample as stable.
    """
    payload = {
        "history": history,
        "projected_role": projected_role,
        "availability_probability": availability_probability,
    }
    _reject_market_inputs(payload)
    if not entity_id:
        raise PropChallengerError("ENTITY_ID_REQUIRED")
    if not 0.0 < decay <= 1.0:
        raise PropChallengerError("BAD_DECAY")
    if shrink_games < 0 or min_history_games < 0:
        raise PropChallengerError("BAD_SHRINKAGE_CONFIG")
    availability = _prob(availability_probability, "availability_probability")

    metrics = ("pass_attempts", "rush_attempts", "targets")
    priors: dict[str, float] = {}
    estimates: dict[str, float] = {}
    used_history = 0
    for metric in metrics:
        prior = _finite(projected_role.get(metric, 0.0), f"projected_role.{metric}")
        if prior < 0:
            raise PropChallengerError(f"NEGATIVE_ROLE_PRIOR:{metric}")
        priors[metric] = prior
        observed: list[float] = []
        for row in history:
            if metric not in row:
                continue
            value = _finite(row[metric], f"history.{metric}")
            if value < 0:
                raise PropChallengerError(f"NEGATIVE_HISTORY:{metric}")
            observed.append(value)
        used_history = max(used_history, len(observed))
        if not observed:
            estimates[metric] = prior
            continue
        hist_mean, hist_weight = _weighted_mean(observed, decay)
        estimates[metric] = (
            hist_mean * hist_weight + prior * shrink_games
        ) / max(hist_weight + shrink_games, 1e-12)

    source = "HISTORY_BLEND" if used_history >= min_history_games else "PROJECTED_ROLE"
    return RoleProjection(
        entity_id=entity_id,
        pass_attempt_mean=max(0.0, estimates["pass_attempts"] * availability),
        rush_attempt_mean=max(0.0, estimates["rush_attempts"] * availability),
        target_mean=max(0.0, estimates["targets"] * availability),
        availability_probability=availability,
        history_games=used_history,
        source=source,
    )


def apply_context(role: RoleProjection, context: Mapping[str, Any]) -> RoleProjection:
    """Apply preregisterable football context, never sportsbook market inputs.

    Expected multipliers can encode opponent efficiency, PROE/game plan,
    weather, injury/depth-chart role, and non-market game-state expectations.
    """
    _reject_market_inputs(context)
    pass_mult = _finite(context.get("pass_volume_multiplier", 1.0), "pass_volume_multiplier")
    rush_mult = _finite(context.get("rush_volume_multiplier", 1.0), "rush_volume_multiplier")
    target_mult = _finite(context.get("target_multiplier", 1.0), "target_multiplier")
    for name, value in (("pass", pass_mult), ("rush", rush_mult), ("target", target_mult)):
        if value < 0:
            raise PropChallengerError(f"NEGATIVE_CONTEXT_MULTIPLIER:{name}")
    return RoleProjection(
        entity_id=role.entity_id,
        pass_attempt_mean=role.pass_attempt_mean * pass_mult,
        rush_attempt_mean=role.rush_attempt_mean * rush_mult,
        target_mean=role.target_mean * target_mult,
        availability_probability=role.availability_probability,
        history_games=role.history_games,
        source=role.source,
    )


def _poisson(rng: random.Random, mean: float) -> int:
    mean = max(0.0, float(mean))
    if mean <= 0.0:
        return 0
    if mean > 30.0:
        return max(0, round(rng.gauss(mean, mean ** 0.5)))
    limit = exp(-mean)
    product = 1.0
    k = 0
    while product > limit:
        k += 1
        product *= rng.random()
    return k - 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    p = min(1.0, max(0.0, float(p)))
    return sum(rng.random() < p for _ in range(max(0, int(n))))


def _gamma_sum(rng: random.Random, n: int, mean_per_event: float, cv: float) -> float:
    if n <= 0 or mean_per_event <= 0:
        return 0.0
    cv = max(0.05, float(cv))
    shape = max(0.1, 1.0 / (cv * cv))
    scale = float(mean_per_event) / shape
    return sum(rng.gammavariate(shape, scale) for _ in range(n))


@dataclass(frozen=True)
class PropSimulation:
    entity_id: str
    paths: tuple[dict[str, int], ...]
    seed: int
    model_id: str = MODEL_ID
    status: str = STATUS
    authority_footer: str = AUTHORITY_FOOTER

    @property
    def sha256(self) -> str:
        raw = json.dumps(self.paths, sort_keys=True, separators=(",", ":")).encode()
        return sha256(raw).hexdigest()

    def probabilities(self, market: str, line: float) -> tuple[float, float, float]:
        metric = SUPPORTED_MARKETS.get(str(market).upper())
        if metric is None:
            raise PropChallengerError(f"UNSUPPORTED_PROP_MARKET:{market}")
        threshold = _finite(line, "line")
        n = len(self.paths)
        if n == 0:
            raise PropChallengerError("EMPTY_SIMULATION")
        over = sum(float(row[metric]) > threshold for row in self.paths) / n
        under = sum(float(row[metric]) < threshold for row in self.paths) / n
        push = max(0.0, 1.0 - over - under)
        return over, under, push


def simulate_player_props(
    *,
    role: RoleProjection,
    efficiency: Mapping[str, Any],
    paths: int = 50_000,
    seed: int = 1,
    shared_pace_sigma: float = 0.12,
) -> PropSimulation:
    """Generate one shared player distribution for all ten supported prop families."""
    _reject_market_inputs(efficiency)
    if paths < 100:
        raise PropChallengerError("TOO_FEW_PATHS")
    sigma = _finite(shared_pace_sigma, "shared_pace_sigma")
    if sigma < 0 or sigma > 1:
        raise PropChallengerError("BAD_SHARED_PACE_SIGMA")

    completion_rate = _prob(efficiency["completion_rate"], "completion_rate")
    catch_rate = _prob(efficiency["catch_rate"], "catch_rate")
    pass_td_rate = _prob(efficiency["pass_td_rate"], "pass_td_rate")
    interception_rate = _prob(efficiency["interception_rate"], "interception_rate")
    ypa = _finite(efficiency["yards_per_attempt"], "yards_per_attempt")
    ypc = _finite(efficiency["yards_per_carry"], "yards_per_carry")
    ypt = _finite(efficiency["yards_per_target"], "yards_per_target")
    if min(ypa, ypc, ypt) < 0:
        raise PropChallengerError("NEGATIVE_EFFICIENCY")
    pass_cv = _finite(efficiency.get("passing_yards_cv", 0.80), "passing_yards_cv")
    rush_cv = _finite(efficiency.get("rushing_yards_cv", 0.75), "rushing_yards_cv")
    rec_cv = _finite(efficiency.get("receiving_yards_cv", 0.90), "receiving_yards_cv")
    if min(pass_cv, rush_cv, rec_cv) <= 0:
        raise PropChallengerError("BAD_YARDAGE_CV")

    rng = random.Random(int(seed))
    out: list[dict[str, int]] = []
    for _ in range(paths):
        z = rng.gauss(0.0, 1.0)
        shared = exp(sigma * z - 0.5 * sigma * sigma)
        pass_attempts = _poisson(rng, role.pass_attempt_mean * shared)
        rush_attempts = _poisson(rng, role.rush_attempt_mean * shared)
        targets = _poisson(rng, role.target_mean * shared)

        completions = _binomial(rng, pass_attempts, completion_rate)
        passing_yards = round(_gamma_sum(rng, pass_attempts, ypa, pass_cv))
        passing_tds = _binomial(rng, pass_attempts, pass_td_rate)
        interceptions = _binomial(rng, pass_attempts, interception_rate)

        rushing_yards = round(_gamma_sum(rng, rush_attempts, ypc, rush_cv))
        receptions = _binomial(rng, targets, catch_rate)
        yards_per_reception = 0.0 if catch_rate <= 0 else ypt / max(catch_rate, 1e-9)
        receiving_yards = round(_gamma_sum(rng, receptions, yards_per_reception, rec_cv))

        out.append({
            "pass_attempts": pass_attempts,
            "completions": completions,
            "passing_yards": passing_yards,
            "passing_tds": passing_tds,
            "interceptions": interceptions,
            "rush_attempts": rush_attempts,
            "rushing_yards": rushing_yards,
            "targets": targets,
            "receptions": receptions,
            "receiving_yards": receiving_yards,
            "rush_receiving_yards": rushing_yards + receiving_yards,
        })
    return PropSimulation(role.entity_id, tuple(out), int(seed))


def _parse_time(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PropChallengerError(f"BAD_TIMESTAMP:{name}") from exc
    if dt.tzinfo is None:
        raise PropChallengerError(f"TIMESTAMP_TIMEZONE_MISSING:{name}")
    return dt.astimezone(timezone.utc)


def _quote_price(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or -99 <= value <= 99:
        raise PropChallengerError(f"BAD_AMERICAN_ODDS:{name}")
    return value


def _normalize_quote(quote: Mapping[str, Any], *, expected_side: str, line: float) -> dict[str, Any]:
    side = str(quote.get("side", "")).upper()
    if side != expected_side:
        raise PropChallengerError(f"BAD_QUOTE_SIDE:{expected_side}")
    qline = _finite(quote.get("line"), f"{expected_side}.line")
    if qline != float(line):
        raise PropChallengerError("PAIRED_QUOTE_LINE_MISMATCH")
    book = str(quote.get("book", "")).strip()
    if not book:
        raise PropChallengerError("QUOTE_BOOK_REQUIRED")
    return {
        "side": side,
        "line": qline,
        "book": book,
        "price": _quote_price(quote.get("price"), f"{expected_side}.price"),
        "retrieved_at": _parse_time(quote.get("retrieved_at"), f"{expected_side}.retrieved_at"),
    }


@dataclass(frozen=True)
class PropQuoteEvaluation:
    entity_id: str
    market: str
    side: str
    line: float
    book: str
    price_american: int
    estimate_p: float
    estimate_p_nonpush: float
    push_p: float
    market_no_vig_p: float
    edge_probability_points: float
    ev_per_dollar: float
    devig_method: str = "POWER_V1"
    status: str = STATUS
    official: bool = False
    staking_authority: bool = False
    authority_footer: str = AUTHORITY_FOOTER


def evaluate_paired_quote(
    *,
    simulation: PropSimulation,
    market: str,
    side: str,
    line: float,
    over_quote: Mapping[str, Any],
    under_quote: Mapping[str, Any],
    as_of: Any,
    ttl_seconds: int = QUOTE_TTL_SECONDS,
    max_skew_seconds: int = MAX_QUOTE_SKEW_SECONDS,
) -> PropQuoteEvaluation:
    """Bind an estimate to a same-book/same-line two-sided quote after simulation.

    Missing/one-sided prices are refused by signature and validation. POWER_V1
    is used for the no-vig baseline, including the existing +400 sensitivity
    guard in ``sports.common.ev_math``.
    """
    market = str(market).upper()
    if market not in SUPPORTED_MARKETS:
        raise PropChallengerError(f"UNSUPPORTED_PROP_MARKET:{market}")
    side = str(side).upper()
    if side not in {"OVER", "UNDER"}:
        raise PropChallengerError("SIDE_MUST_BE_OVER_OR_UNDER")
    bound_line = _finite(line, "line")
    over = _normalize_quote(over_quote, expected_side="OVER", line=bound_line)
    under = _normalize_quote(under_quote, expected_side="UNDER", line=bound_line)
    if over["book"] != under["book"]:
        raise PropChallengerError("PAIRED_QUOTE_BOOK_MISMATCH")

    now = _parse_time(as_of, "as_of")
    for quote in (over, under):
        age = (now - quote["retrieved_at"]).total_seconds()
        if age > ttl_seconds:
            raise PropChallengerError("QUOTE_STALE")
        if age < -max_skew_seconds:
            raise PropChallengerError("QUOTE_CLOCK_SKEW")
    if abs((over["retrieved_at"] - under["retrieved_at"]).total_seconds()) > max_skew_seconds:
        raise PropChallengerError("PAIRED_QUOTE_TIME_SKEW")

    over_p, under_p, push_p = simulation.probabilities(market, bound_line)
    win_p, loss_p = (over_p, under_p) if side == "OVER" else (under_p, over_p)
    nonpush = win_p + loss_p
    estimate_nonpush = win_p / nonpush if nonpush > 0 else 0.5

    try:
        over_dec = american_to_decimal(over["price"])
        under_dec = american_to_decimal(under["price"])
        fair = devig([over_dec, under_dec], trigger_american=400, max_spread_pp=1.0)
    except EVError as exc:
        raise PropChallengerError(exc.code) from exc
    market_p = fair[0] if side == "OVER" else fair[1]
    chosen = over if side == "OVER" else under
    chosen_dec = american_to_decimal(chosen["price"])
    ev = win_p * (chosen_dec - 1.0) - loss_p
    edge_pp = 100.0 * (estimate_nonpush - market_p)

    return PropQuoteEvaluation(
        entity_id=simulation.entity_id,
        market=market,
        side=side,
        line=bound_line,
        book=chosen["book"],
        price_american=chosen["price"],
        estimate_p=win_p,
        estimate_p_nonpush=estimate_nonpush,
        push_p=push_p,
        market_no_vig_p=market_p,
        edge_probability_points=edge_pp,
        ev_per_dollar=ev,
    )


def diagnostic_tags(
    *,
    role: RoleProjection,
    football_context: Mapping[str, Any] | None = None,
    market_context: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Explanation-only tags. They never alter role, simulation, or estimate_p."""
    football_context = football_context or {}
    market_context = market_context or {}
    tags: list[str] = []
    if role.source == "PROJECTED_ROLE":
        tags.append("PROJECTED_ROLE")
    if role.history_games < 3:
        tags.append("LOW_TRAILING_SAMPLE")
    wind = football_context.get("wind_mph")
    if wind is not None and _finite(wind, "wind_mph") >= 15:
        tags.append("HIGH_WIND")
    depth = market_context.get("book_count")
    if depth is not None:
        count = int(_finite(depth, "book_count"))
        tags.append("DEEP_MARKET" if count >= 5 else "THIN_MARKET")
    return tuple(tags)
