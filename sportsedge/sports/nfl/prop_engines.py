"""Governed NFL player-prop candidate engines.

These engines create genuine model probabilities from PIT-bound player history.
They are EXPERIMENTAL and non-promoting until market-specific validation earns
eligibility. Sportsbook lines/prices are evaluation inputs only and are never
accepted by fit().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import erf, exp, floor, isfinite, lgamma, log, sqrt
from typing import Any, Iterable, Mapping

ENGINE_CONTRACT = "NFL_PLAYER_PROP_ENGINES_V1"
MODEL_P_STATUS = "EXPERIMENTAL_MODEL_P"

MARKETS: dict[str, tuple[str, str]] = {
    "ANYTIME_TD": ("anytime_td", "bernoulli"),
    "RECEPTIONS": ("receptions", "count"),
    "RECEIVING_YARDS": ("receiving_yards", "continuous"),
    "TARGETS": ("targets", "count"),
    "RUSHING_YARDS": ("rushing_yards", "continuous"),
    "RUSH_ATTEMPTS": ("carries", "count"),
    "PASSING_YARDS": ("passing_yards", "continuous"),
    "PASS_ATTEMPTS": ("attempts", "count"),
    "COMPLETIONS": ("completions", "count"),
    "PASSING_TDS": ("passing_tds", "count"),
    "INTERCEPTIONS": ("passing_interceptions", "count"),
}

_MARKET_KEYS = {
    "line", "prop_line", "price", "odds", "over_odds", "under_odds",
    "sportsbook", "book", "implied_probability", "market_probability",
    "tickets", "handle", "consensus", "closing_line", "closing_price",
}

_PASSING = {"PASSING_YARDS", "PASS_ATTEMPTS", "COMPLETIONS", "PASSING_TDS", "INTERCEPTIONS"}


class PropEngineError(ValueError):
    pass


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        try:
            out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise PropEngineError("PROP_TIMESTAMP_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise PropEngineError("PROP_TIMESTAMP_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _finite(value: Any, reason: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PropEngineError(reason) from exc
    if not isfinite(out):
        raise PropEngineError(reason)
    return out


def _assert_market_blind(row: Mapping[str, Any]) -> None:
    stack = [row]
    while stack:
        current = stack.pop()
        for key, value in current.items():
            if str(key).strip().lower() in _MARKET_KEYS:
                raise PropEngineError(f"PROP_MARKET_DATA_PROHIBITED:{key}")
            if isinstance(value, Mapping):
                stack.append(value)


def _sha(value: str) -> str:
    out = str(value or "").strip().lower()
    if len(out) != 64:
        raise PropEngineError("PROP_SOURCE_MANIFEST_SHA256_INVALID")
    try:
        int(out, 16)
    except ValueError as exc:
        raise PropEngineError("PROP_SOURCE_MANIFEST_SHA256_INVALID") from exc
    return out


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _poisson_pmf(k: int, mean: float) -> float:
    if k < 0:
        return 0.0
    return exp(-mean + k * log(mean) - lgamma(k + 1.0)) if mean > 0 else (1.0 if k == 0 else 0.0)


def _nb_pmf(k: int, mean: float, variance: float) -> float:
    if k < 0:
        return 0.0
    if variance <= mean + 1e-9:
        return _poisson_pmf(k, mean)
    r = mean * mean / (variance - mean)
    p = r / (r + mean)
    return exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1.0) + r * log(p) + k * log(1.0 - p))


def _count_cdf(k: int, mean: float, variance: float) -> float:
    if k < 0:
        return 0.0
    return min(1.0, sum(_nb_pmf(i, mean, variance) for i in range(k + 1)))


def _weighted(values: list[float], decay: float) -> tuple[float, float, float]:
    # Fixed predeclared recency decay; not selected against held-out prop results.
    weights = [decay ** (len(values) - 1 - i) for i in range(len(values))]
    total = sum(weights)
    mean = sum(w * x for w, x in zip(weights, values)) / total
    variance = sum(w * (x - mean) ** 2 for w, x in zip(weights, values)) / total
    zero = sum(w for w, x in zip(weights, values) if x == 0.0) / total
    return mean, variance, zero


@dataclass(frozen=True)
class NFLPropEngineModel:
    contract: str
    model_id: str
    model_p_status: str
    player_id: str
    market_id: str
    family: str
    stat_field: str
    as_of: str
    sample_n: int
    weighted_mean: float
    weighted_variance: float
    zero_probability: float
    td_alpha: float | None
    td_beta: float | None
    source_manifest_sha256: str
    recency_decay: float
    promotion_eligible: bool = False
    truth_gate_eligible: bool = False


@dataclass(frozen=True)
class NFLPropPrediction:
    contract: str
    model_id: str
    model_p_status: str
    player_id: str
    market_id: str
    side: str
    line: float | None
    model_probability: float
    push_probability: float
    fair_american_odds: int | None
    promotion_eligible: bool = False
    truth_gate_eligible: bool = False


def _fair_american(p: float) -> int | None:
    if p <= 0.0 or p >= 1.0:
        return None
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def fit_nfl_prop_engine(
    history_rows: Iterable[Mapping[str, Any]],
    *,
    player_id: str,
    market_id: str,
    as_of: Any,
    source_manifest_sha256: str,
    min_games: int = 6,
    recency_decay: float = 0.90,
) -> NFLPropEngineModel:
    market = str(market_id or "").strip().upper()
    if market not in MARKETS:
        raise PropEngineError(f"PROP_MARKET_UNSUPPORTED:{market}")
    pid = str(player_id or "").strip()
    if not pid:
        raise PropEngineError("PROP_PLAYER_ID_REQUIRED")
    pit = _utc(as_of)
    manifest = _sha(source_manifest_sha256)
    if not (0.0 < recency_decay <= 1.0):
        raise PropEngineError("PROP_RECENCY_DECAY_INVALID")

    stat_field, family = MARKETS[market]
    games: list[tuple[datetime, str, float]] = []
    for raw in history_rows:
        row = dict(raw)
        _assert_market_blind(row)
        if str(row.get("player_id") or "").strip() != pid:
            continue
        kickoff = _utc(row.get("kickoff_ts"))
        if kickoff >= pit:
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            raise PropEngineError("PROP_GAME_ID_REQUIRED")
        if market == "ANYTIME_TD":
            rush_td = _finite(row.get("rushing_tds", 0), "PROP_RUSH_TD_INVALID")
            recv_td = _finite(row.get("receiving_tds", 0), "PROP_RECV_TD_INVALID")
            value = 1.0 if rush_td + recv_td > 0.0 else 0.0
        else:
            if row.get(stat_field) in (None, ""):
                raise PropEngineError(f"PROP_STAT_MISSING:{stat_field}:{game_id}")
            value = _finite(row.get(stat_field), f"PROP_STAT_INVALID:{stat_field}:{game_id}")
            if value < 0.0:
                raise PropEngineError(f"PROP_STAT_NEGATIVE:{stat_field}:{game_id}")
        games.append((kickoff, game_id, value))

    games.sort(key=lambda item: (item[0], item[1]))
    if len({game_id for _, game_id, _ in games}) != len(games):
        raise PropEngineError("PROP_DUPLICATE_PLAYER_GAME")
    if len(games) < int(min_games):
        raise PropEngineError(f"PROP_HISTORY_INSUFFICIENT:{len(games)}:{min_games}")
    values = [value for _, _, value in games]
    mean, variance, zero = _weighted(values, recency_decay)

    alpha = beta = None
    if family == "bernoulli":
        # Weighted Beta(1,1) posterior. Effective weighted successes/failures are
        # based only on PIT outcomes; the sportsbook price never enters here.
        weights = [recency_decay ** (len(values) - 1 - i) for i in range(len(values))]
        successes = sum(w * x for w, x in zip(weights, values))
        failures = sum(w * (1.0 - x) for w, x in zip(weights, values))
        alpha = 1.0 + successes
        beta = 1.0 + failures
        mean = alpha / (alpha + beta)
        variance = mean * (1.0 - mean)
        zero = 1.0 - mean

    return NFLPropEngineModel(
        contract=ENGINE_CONTRACT,
        model_id=f"nfl_prop_{market.lower()}_v1",
        model_p_status=MODEL_P_STATUS,
        player_id=pid,
        market_id=market,
        family=family,
        stat_field=stat_field,
        as_of=pit.isoformat(),
        sample_n=len(values),
        weighted_mean=float(mean),
        weighted_variance=float(max(variance, 1e-9)),
        zero_probability=float(min(1.0, max(0.0, zero))),
        td_alpha=alpha,
        td_beta=beta,
        source_manifest_sha256=manifest,
        recency_decay=float(recency_decay),
        promotion_eligible=False,
        truth_gate_eligible=False,
    )


def predict_nfl_prop(
    model: NFLPropEngineModel,
    *,
    side: str,
    line: float | None = None,
    availability_status: str,
    role_confirmed: bool,
    starting_qb_confirmed: bool | None = None,
) -> NFLPropPrediction:
    if model.contract != ENGINE_CONTRACT or model.promotion_eligible or model.truth_gate_eligible:
        raise PropEngineError("PROP_ENGINE_GOVERNANCE_INVALID")
    status = str(availability_status or "").strip().upper()
    if status not in {"ACTIVE", "EXPECTED_ACTIVE"}:
        raise PropEngineError(f"PROP_PLAYER_AVAILABILITY_BLOCKED:{status or 'MISSING'}")
    if role_confirmed is not True:
        raise PropEngineError("PROP_ROLE_UNCONFIRMED")
    if model.market_id in _PASSING and starting_qb_confirmed is not True:
        raise PropEngineError("PROP_STARTING_QB_UNCONFIRMED")

    direction = str(side or "").strip().upper()
    push = 0.0
    if model.family == "bernoulli":
        if model.market_id != "ANYTIME_TD" or line is not None:
            raise PropEngineError("PROP_ANYTIME_TD_LINE_MUST_BE_NONE")
        if direction not in {"YES", "NO"}:
            raise PropEngineError("PROP_ANYTIME_TD_SIDE_INVALID")
        yes = model.weighted_mean
        probability = yes if direction == "YES" else 1.0 - yes
        normalized_line = None
    else:
        if direction not in {"OVER", "UNDER"}:
            raise PropEngineError("PROP_SIDE_INVALID")
        if line is None:
            raise PropEngineError("PROP_LINE_REQUIRED")
        threshold = _finite(line, "PROP_LINE_INVALID")
        normalized_line = threshold
        if model.family == "count":
            lower = floor(threshold)
            cdf_lower = _count_cdf(lower, model.weighted_mean, model.weighted_variance)
            if float(threshold).is_integer():
                point = _nb_pmf(int(threshold), model.weighted_mean, model.weighted_variance)
                push = point
                over = 1.0 - cdf_lower
                under = max(0.0, cdf_lower - point)
            else:
                over = 1.0 - cdf_lower
                under = cdf_lower
            probability = over if direction == "OVER" else under
        else:
            # Zero-inflated normal approximation for nonnegative yardage. Positive
            # component moments are inferred from PIT history; no line is used in fit.
            z = model.zero_probability
            positive_mean = model.weighted_mean / max(1e-9, 1.0 - z)
            positive_var = max(1.0, model.weighted_variance)
            sigma = sqrt(positive_var)
            positive_cdf = _normal_cdf((threshold - positive_mean) / sigma)
            under = z + (1.0 - z) * positive_cdf if threshold > 0 else 0.0
            over = 1.0 - under
            probability = over if direction == "OVER" else under

    probability = min(1.0, max(0.0, float(probability)))
    return NFLPropPrediction(
        contract=ENGINE_CONTRACT,
        model_id=model.model_id,
        model_p_status=model.model_p_status,
        player_id=model.player_id,
        market_id=model.market_id,
        side=direction,
        line=normalized_line,
        model_probability=probability,
        push_probability=float(push),
        fair_american_odds=_fair_american(probability),
        promotion_eligible=False,
        truth_gate_eligible=False,
    )
