"""NFL market-anchored residual pricing, strictly research-only.

Market and quote intake are inputs to the *pricing layer*, never to the
independent frozen score model. A score grid for both the market anchor and
residual location removes the frozen distribution's baseline skew: a zero
residual implies exactly zero incremental no-vig edge, including pushes.

No refit, promotion, Model_P, Truth Gate, OFFICIAL or staking authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp, isfinite, log
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

from sports.common.ev_math import EVError, american_to_decimal, devig
from sportsedge.sports.nfl.discrete_v2 import (
    MEAN_CEILING, MEAN_FLOOR, load_freeze, means_from_attempt9, score_grid,
)
from sportsedge.sports.nfl.unified_market_engine import price_game_market

DEFAULT_FIT = Path(__file__).resolve().parents[3] / "config" / "nfl_market_residual_research_v1.json"
SCHEMA = "NFL_MARKET_RESIDUAL_RESEARCH_V1"
SUPPORTED = ("moneyline", "spread", "total")


class NFLResidualError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise NFLResidualError(f"{field}:FINITE_REQUIRED")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise NFLResidualError(f"{field}:FINITE_REQUIRED") from exc
    if not isfinite(number):
        raise NFLResidualError(f"{field}:FINITE_REQUIRED")
    return number


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError) as exc:
        raise NFLResidualError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLResidualError(f"{field}:AWARE_TIMESTAMP_REQUIRED")
    return dt.astimezone(timezone.utc)


def _american(value: Any) -> int:
    number = _num(value, "price")
    if int(number) != number or -100 < number < 100:
        raise NFLResidualError("PAIRED_PRICE_INVALID")
    return int(number)


def load_fit(path: Path | None = None) -> dict[str, Any]:
    try:
        fit = json.loads((path or DEFAULT_FIT).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise NFLResidualError("RESIDUAL_FIT_UNAVAILABLE") from exc
    if not isinstance(fit, dict) or fit.get("schema") != SCHEMA:
        raise NFLResidualError("RESIDUAL_FIT_SCHEMA_INVALID")
    if fit.get("status") != "PREDECLARED_RESEARCH_ONLY_NOT_FITTED":
        raise NFLResidualError("RESIDUAL_FIT_STATUS_INVALID")
    for family in ("margin", "total"):
        coeffs = fit.get(family)
        if not isinstance(coeffs, dict):
            raise NFLResidualError(f"RESIDUAL_FIT_MISSING:{family}")
        intercept = _num(coeffs.get("intercept"), family + "_intercept")
        weight = _num(coeffs.get("weight"), family + "_weight")
        if abs(intercept) > 2.0 or not 0.0 <= weight <= 0.25:
            raise NFLResidualError(f"RESIDUAL_FIT_NOT_CONSERVATIVE:{family}")
    if not 0 < _num(fit.get("forward_min_abs_adjustment_points"), "forward_min") <= 3:
        raise NFLResidualError("FORWARD_MIN_INVALID")
    if not 0 < _num(fit.get("max_quote_age_seconds"), "quote_age") <= 600:
        raise NFLResidualError("QUOTE_TTL_MAY_NOT_LOOSEN")
    if fit.get("no_vig_method") != "POWER_V1":
        raise NFLResidualError("NO_VIG_POLICY_MISMATCH")
    if fit.get("validated_markets") != [] or fit.get("forward_clv_positive") is not False:
        raise NFLResidualError("RESIDUAL_UNAUTHORIZED_PROMOTION")
    auth = fit.get("authority") or {}
    if auth.get("research_only") is not True or any(auth.get(k) is not False
        for k in ("model_p", "truth_gate", "official", "promotion", "staking")):
        raise NFLResidualError("RESIDUAL_UNAUTHORIZED_AUTHORITY")
    return fit


def anchor_game(*, raw_margin: Any, raw_total: Any,
                market_margin: Any, market_total: Any,
                fit: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Home margin positive when the home team is favored.

    Away handicap +3.5 => market home margin +3.5.
    """
    fit = fit if fit is not None else load_fit()
    raw_m = _num(raw_margin, "raw_margin")
    raw_t = _num(raw_total, "raw_total")
    book_m = _num(market_margin, "market_margin")
    book_t = _num(market_total, "market_total")
    if raw_t <= 0 or book_t <= 0:
        raise NFLResidualError("TOTAL_POSITIVE_REQUIRED")
    margin = book_m + _num(fit["margin"]["intercept"],"margin_intercept") + (
        _num(fit["margin"]["weight"],"margin_weight") * (raw_m-book_m)
    )
    total = book_t + _num(fit["total"]["intercept"],"total_intercept") + (
        _num(fit["total"]["weight"],"total_weight") * (raw_t-book_t)
    )
    if not isfinite(margin) or not isfinite(total):
        raise NFLResidualError("RESIDUAL_NONFINITE")
    home = (total + margin)/2.0
    away = (total - margin)/2.0
    if not all(MEAN_FLOOR <= n <= MEAN_CEILING for n in (home,away)):
        raise NFLResidualError("RESIDUAL_GRID_MEANS_OUT_OF_RANGE")
    return {
        "raw_margin":raw_m, "raw_total":raw_t,
        "market_margin":book_m, "market_total":book_t,
        "margin":margin, "total":total,
        "home_mean":home, "away_mean":away,
        "margin_adjustment":margin-book_m, "total_adjustment":total-book_t,
    }


def _logit(prob: float) -> float:
    p = _num(prob, "probability")
    if not 0.0 < p < 1.0:
        raise NFLResidualError("CONDITIONAL_PROBABILITY_INVALID")
    return log(p/(1.0-p))


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    z = exp(value)
    return z/(1.0+z)


def _conditional(row: Mapping[str, Any]) -> float:
    win = _num(row.get("estimate_p"),"grid_win_p")
    push = _num(row.get("push_p"),"grid_push_p")
    if not 0.0 <= push < 1.0 or not 0.0 < win < 1.0-push:
        raise NFLResidualError("GRID_CONDITIONAL_UNPRICEABLE")
    return win/(1.0-push)


def _pair(market: Mapping[str, Any], *, name: str, observed: datetime,
          now: datetime, age_limit: float) -> tuple[int,int]:
    timestamp = _utc(market.get("quote_retrieved_at"), name+"_quote")
    seconds = (now-timestamp).total_seconds()
    if not 0 <= seconds <= age_limit or timestamp > observed:
        raise NFLResidualError(f"QUOTE_STALE_OR_NOT_ASOF:{name}")
    a = _american(market.get("away_or_over_price"))
    b = _american(market.get("home_or_under_price"))
    try:
        probs = devig([american_to_decimal(a), american_to_decimal(b)],
                      trigger_american=400,max_spread_pp=1.0)
    except (EVError, ValueError, TypeError) as exc:
        raise NFLResidualError(f"PAIRED_NO_VIG_INVALID:{name}") from exc
    if len(probs) != 2 or not all(0 < p < 1 and isfinite(p) for p in probs):
        raise NFLResidualError(f"PAIRED_NO_VIG_INVALID:{name}")
    return a,b


def price_game_from_pairs(*, raw_margin: Any, raw_total: Any,
                          markets: Sequence[Mapping[str, Any]],
                          observed_at: Any, as_of: Any, kickoff_at: Any,
                          fit: Mapping[str, Any] | None = None,
                          model_family: str = "ATTEMPT9_RAW") -> dict[str, Any]:
    """Game market research using the SAME frozen discrete score shape.

    Requires *paired* and fresh spread+total to identify the anchor; optional
    moneyline is scored from the same grid. Both sides of every included quote
    must be present and from the same intake observation. No paid data requests.
    """
    config = fit if fit is not None else load_fit()
    now = _utc(as_of, "as_of")
    observed = _utc(observed_at, "observed_at")
    kickoff = _utc(kickoff_at, "kickoff_at")
    if observed > now or kickoff <= now:
        raise NFLResidualError("NOT_PREKICKOFF_ASOF")
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in markets:
        if not isinstance(row, Mapping):
            raise NFLResidualError("MARKET_QUOTE_OBJECT_REQUIRED")
        name = str(row.get("market") or "").strip().lower()
        if name not in SUPPORTED:
            continue
        if name in indexed:
            raise NFLResidualError(f"DUPLICATE_GAME_MARKET:{name}")
        indexed[name] = row
    if not {"spread","total"}.issubset(indexed):
        raise NFLResidualError("PAIRED_SPREAD_TOTAL_REQUIRED")
    for name,row in indexed.items():
        _pair(row,name=name,observed=observed,now=now,
              age_limit=_num(config["max_quote_age_seconds"],"quote_age"))
    away_line = _num(indexed["spread"].get("line"),"away_handicap")
    total_line = _num(indexed["total"].get("line"),"total_line")
    if "moneyline" in indexed and indexed["moneyline"].get("line") is not None:
        raise NFLResidualError("MONEYLINE_LINE_MUST_BE_NULL")
    anchored = anchor_game(raw_margin=raw_margin,raw_total=raw_total,
                           market_margin=away_line,market_total=total_line,fit=config)
    market_home = (total_line+away_line)/2.0
    market_away = (total_line-away_line)/2.0
    if not all(MEAN_FLOOR <= n <= MEAN_CEILING for n in (market_home,market_away)):
        raise NFLResidualError("MARKET_GRID_MEANS_OUT_OF_RANGE")
    # Freeze loaded once: identical score shape and same seeded distribution.
    freeze = load_freeze()
    book_grid = score_grid(market_home,market_away,freeze)
    model_grid = score_grid(anchored["home_mean"],anchored["away_mean"],freeze)
    result = []
    for name,row in indexed.items():
        prices = (_american(row["away_or_over_price"]),
                  _american(row["home_or_under_price"]))
        no_vig = devig([american_to_decimal(prices[0]),
                        american_to_decimal(prices[1])],
                       trigger_american=400,max_spread_pp=1.0)
        rows = []
        for side_index,selection in enumerate(
            ("over","under") if name=="total" else ("away","home")
        ):
            request = {"market":name,"selection":selection}
            if name == "spread":
                request["line"] = away_line if side_index == 0 else -away_line
            if name == "total":
                request["line"] = total_line
            baseline = price_game_market(book_grid,request)
            shifted = price_game_market(model_grid,request)
            market_p = float(no_vig[side_index])
            # Delta log odds relative to the *same* frozen grid at market
            # center; avoids manufactured EV from the frozen grid's baseline
            # skew/tie spikes when the independent model residual is zero.
            delta = _logit(_conditional(shifted))-_logit(_conditional(baseline))
            fair_conditional_p = _logistic(_logit(market_p)+delta)
            push = float(shifted["push_p"])
            win = fair_conditional_p*(1.0-push)
            price = prices[side_index]
            ev = win*american_to_decimal(price)-(1.0-push)
            rows.append({
                "selection":selection, "line":request.get("line"),
                "price_american":price,
                "estimate_p":win, "conditional_win_probability":fair_conditional_p,
                "market_no_vig_p":market_p,
                "edge_probability_points":fair_conditional_p-market_p,
                "ev_per_dollar":ev, "push_p":push,
                "loss_p":1.0-push-win,
                "fair_american":(-100*fair_conditional_p/(1-fair_conditional_p)
                                 if fair_conditional_p>=0.5
                                 else 100*(1-fair_conditional_p)/fair_conditional_p),
                "research_only":True, "bet_eligible":False, "official":False,
            })
        result.append({"market":name, "line":row.get("line"), "sides":rows,
                       "quote_retrieved_at":row.get("quote_retrieved_at"),
                       "devig_method":"POWER_V1",
                       "status":"RESEARCH_ONLY_NOT_FORWARD_VALIDATED"})
    threshold = _num(config["forward_min_abs_adjustment_points"],"forward_min")
    return {
        "schema":SCHEMA, "status":"RESEARCH_ONLY",
        "model_family":str(model_family),
        "center":anchored,
        "markets":result,
        "forward_track_min_abs_adjustment_points":threshold,
        "forward_track_signal":(
            abs(anchored["margin_adjustment"]) >= threshold
            or abs(anchored["total_adjustment"]) >= threshold
        ),
        "validated_markets":[],
        "authority":{"research_only":True, "model_p":False, "truth_gate":False,
                     "official":False, "promotion":False,"staking":False},
        "evidence":"PREDECLARED_SHRINKAGE_NOT_FORWARD_CLV_PROOF",
    }


__all__ = ["SCHEMA","NFLResidualError","load_fit","anchor_game","price_game_from_pairs"]
