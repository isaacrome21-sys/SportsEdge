"""Research-only NFL fair prices: shrink market-blind score location toward the books.

This module intentionally does NOT modify frozen Attempt-9, M2, discrete-v2
or unified phone artifacts. The coefficients are unfitted precommitted research
priors; they are NOT a historical OOS result or prospective positive CLV.

We preserve the frozen discrete joint-score grid shape. To eliminate false
edges from its uncalibrated absolute shape, market_no_vig + (fair_grid_prob -
market_centered_grid_prob) is the *conditional*, zero-at-zero-residual edge.
Push mass comes from the fair grid for integer lines. No betting authority.
"""
from __future__ import annotations

from sportsedge.sports.nfl.score_grid_integrity import validate_score_grid

from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from sports.common.ev_math import devig
from sportsedge.sports.nfl.discrete_v2 import load_freeze, score_grid

POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "nfl_market_anchored_residual_v1.json"
SCHEMA = "SPORTSEDGE_NFL_MARKET_ANCHORED_RESIDUAL_POLICY_V1"
MARKETS = ("moneyline", "spread", "total")
DEVIG_METHOD = "POWER_V1"


class ResidualQuoteError(ValueError):
    pass


def _finite(value: Any, key: str) -> float:
    if value is None or isinstance(value, bool):
        raise ResidualQuoteError(f"{key}:NUMERIC_REQUIRED")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResidualQuoteError(f"{key}:NUMERIC_REQUIRED") from exc
    if not isfinite(result):
        raise ResidualQuoteError(f"{key}:NONFINITE")
    return result


def _clock(value: Any, key: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResidualQuoteError(f"{key}:INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ResidualQuoteError(f"{key}:AWARE_REQUIRED")
    return out.astimezone(timezone.utc)


def _price(value: Any) -> int:
    p = _finite(value, "PAIRED_PRICE_REQUIRED")
    if int(p) != p or (-100 < p < 100):
        raise ResidualQuoteError("PAIRED_PRICE_REQUIRED:INVALID")
    return int(p)


def _decimal(price: int) -> float:
    return 1.0 + (price / 100 if price > 0 else 100 / -price)


def load_frozen_policy(path: Path | None = None) -> dict[str, Any]:
    try:
        cfg = json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResidualQuoteError("RESIDUAL_POLICY_UNAVAILABLE") from exc
    return validate_policy(cfg)


def validate_policy(cfg: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, Mapping):
        raise ResidualQuoteError("RESIDUAL_POLICY_IDENTITY")
    if cfg.get("schema") != SCHEMA or cfg.get("status") != "PRECOMMITTED_RESEARCH_PRIOR_NOT_HISTORICALLY_FITTED":
        raise ResidualQuoteError("RESIDUAL_POLICY_IDENTITY")
    if cfg.get("evidence_role") != "RESEARCH_ONLY_UNFITTED_PRIOR" or cfg.get("validated_markets") != []:
        raise ResidualQuoteError("RESIDUAL_AUTHORITY_ESCALATION")
    authority = cfg.get("authority") or {}
    if any(authority.get(k) is not False for k in ("model_p", "truth_gate", "promotion", "official", "staking")):
        raise ResidualQuoteError("RESIDUAL_AUTHORITY_ESCALATION")
    for kind in ("margin", "total"):
        coefs = (cfg.get("coefficients") or {}).get(kind) or {}
        weight = _finite(coefs.get("weight"), f"{kind}_weight")
        intercept = _finite(coefs.get("intercept"), f"{kind}_intercept")
        if not 0.0 <= weight <= 0.25 or abs(intercept) > 1.0:
            raise ResidualQuoteError("RESIDUAL_COEFFICIENT_OUT_OF_RESEARCH_BOUND")
    if _finite(cfg.get("forward_track_min_abs_adjustment_points"), "threshold") < 0.5:
        raise ResidualQuoteError("RESIDUAL_TRACK_THRESHOLD_LOWERED")
    if _finite(cfg.get("min_edge_probability_points"), "edge_floor") < 0.02:
        raise ResidualQuoteError("RESIDUAL_EDGE_FLOOR_LOWERED")
    if _finite(cfg.get("min_ev_per_dollar"), "ev_floor") < 0.02:
        raise ResidualQuoteError("RESIDUAL_EV_FLOOR_LOWERED")
    if not 0 < _finite(cfg.get("max_quote_age_seconds"), "quote_ttl") <= 180:
        raise ResidualQuoteError("RESIDUAL_TTL_LOOSENED")
    if not 0 <= _finite(cfg.get("max_skew_seconds"), "quote_skew") <= 30:
        raise ResidualQuoteError("RESIDUAL_SKEW_LOOSENED")
    rules = cfg.get("validation") or {}
    if (rules.get("requires_forward_positive_clv") is not True
        or rules.get("season_based_walk_forward_required_for_refit") is not True
        or rules.get("may_use_dev_data_as_forward_proof") is not False):
        raise ResidualQuoteError("RESIDUAL_FORWARD_GOVERNANCE_MISSING")
    return cfg


def anchor_prediction(*, raw_model_margin: Any, raw_model_total: Any,
                      market_margin: Any, market_total: Any,
                      policy: Mapping[str, Any] | None = None) -> dict[str, float]:
    cfg = validate_policy(policy) if policy is not None else load_frozen_policy()
    raw_margin = _finite(raw_model_margin, "raw_model_margin")
    raw_total = _finite(raw_model_total, "raw_model_total")
    market_home_margin = _finite(market_margin, "market_margin")
    book_total = _finite(market_total, "market_total")
    if book_total <= 0:
        raise ResidualQuoteError("MARKET_TOTAL_INVALID")
    m = cfg["coefficients"]["margin"]
    t = cfg["coefficients"]["total"]
    fm = market_home_margin + _finite(m["intercept"], "margin_intercept") + _finite(m["weight"], "margin_weight") * (raw_margin - market_home_margin)
    ft = book_total + _finite(t["intercept"], "total_intercept") + _finite(t["weight"], "total_weight") * (raw_total - book_total)
    home = (ft + fm) / 2
    away = (ft - fm) / 2
    if not (0.5 <= home <= 70 and 0.5 <= away <= 70):
        raise ResidualQuoteError("RESIDUAL_MEANS_OUT_OF_GRID_RANGE")
    return {"fair_margin": fm, "fair_total": ft,
            "mean_home": home, "mean_away": away,
            "market_margin": market_home_margin, "market_total": book_total}


def _pair(row: Mapping[str, Any], *, as_of: datetime, ttl: int, skew: int) -> tuple[int, int]:
    if not isinstance(row, Mapping):
        raise ResidualQuoteError("PAIRED_PRICE_REQUIRED:MARKET_NOT_OBJECT")
    first = _price(row.get("away_or_over_price"))
    second = _price(row.get("home_or_under_price"))
    stamp = _clock(row.get("quote_retrieved_at"), "QUOTE_TIMESTAMP")
    age = (as_of - stamp).total_seconds()
    if age > ttl:
        raise ResidualQuoteError("QUOTE_STALE")
    if age < -skew:
        raise ResidualQuoteError("QUOTE_CLOCK_SKEW")
    return first, second


def _contract_prob(grid: list[list[float]], market: str, side: int, line: float | None) -> tuple[float, float]:
    win = loss = push = 0.0
    for h, row in enumerate(grid):
        for a, p in enumerate(row):
            if not p:
                continue
            if market == "moneyline":
                val = h - a
                if side == 0:
                    val = -val
            elif market == "spread":
                # Away handicap is the canonical posted line.
                val = a - h + float(line) if side == 0 else h - a - float(line)
            else:
                val = h + a - float(line)
                if side == 1:
                    val = -val
            if val > 1e-9:
                win += p
            elif val < -1e-9:
                loss += p
            else:
                push += p
    nonpush = win + loss
    if nonpush <= 1e-12:
        raise ResidualQuoteError("NO_NONPUSH_SCORE_MASS")
    return win / nonpush, push


def price_game(game: Mapping[str, Any], *, raw_model_margin: Any, raw_model_total: Any,
               as_of: Any, policy: Mapping[str, Any] | None = None,
               score_grid_factory=None) -> list[dict[str, Any]]:
    """All offered game-level pairs, conditional fair probability, and push-aware EV.

    Exact zero residual => zero price edge against no-vig book probabilities.
    This remains explicitly research-only regardless of EV, until forward CLV.
    """
    cfg = validate_policy(policy) if policy is not None else load_frozen_policy()
    now = _clock(as_of, "AS_OF")
    kickoff = _clock(game.get("commence_time"), "KICKOFF")
    if kickoff <= now:
        raise ResidualQuoteError("KICKOFF_STARTED")
    markets: dict[str, Mapping[str, Any]] = {}
    for row in game.get("markets") or []:
        if not isinstance(row, Mapping):
            raise ResidualQuoteError("MARKET_NOT_OBJECT")
        key = str(row.get("market") or "").lower()
        if key not in MARKETS:
            continue
        if key in markets:
            raise ResidualQuoteError(f"DUPLICATE_GAME_MARKET:{key}")
        markets[key] = row
    if "spread" not in markets or "total" not in markets:
        raise ResidualQuoteError("MARKET_SPREAD_TOTAL_REQUIRED")
    ttl = int(cfg["max_quote_age_seconds"])
    skew = int(cfg["max_skew_seconds"])
    pairs = {k: _pair(v, as_of=now, ttl=ttl, skew=skew) for k, v in markets.items()}
    clocks = [_clock(v["quote_retrieved_at"], "QUOTE_TIMESTAMP") for v in markets.values()]
    if (max(clocks) - min(clocks)).total_seconds() > skew:
        raise ResidualQuoteError("ANCHOR_QUOTE_TIME_SKEW")
    spread = _finite(markets["spread"].get("line"), "MARKET_SPREAD")
    total = _finite(markets["total"].get("line"), "MARKET_TOTAL")
    if total <= 0:
        raise ResidualQuoteError("MARKET_TOTAL_INVALID")
    if markets.get("moneyline") and markets["moneyline"].get("line") is not None:
        raise ResidualQuoteError("MONEYLINE_LINE_INVALID")
    anchor = anchor_prediction(raw_model_margin=raw_model_margin, raw_model_total=raw_model_total,
                               market_margin=spread, market_total=total, policy=cfg)
    # The baseline is the posted market, with no model intercept applied.
    means = {"mean_home": (total + spread) / 2, "mean_away": (total - spread) / 2}
    if not all(0.5 <= value <= 70 for value in means.values()):
        raise ResidualQuoteError("MARKET_MEANS_OUT_OF_GRID_RANGE")
    freeze = load_freeze()
    grid_factory = score_grid_factory or (lambda home, away: score_grid(home, away, freeze))
    baseline = grid_factory(means["mean_home"], means["mean_away"])
    residual = grid_factory(anchor["mean_home"], anchor["mean_away"])
    # Mass guard (wired t211u): a factory grid with bad mass is refused.
    validate_score_grid(baseline)
    validate_score_grid(residual)
    rows = []
    for key in MARKETS:
        if key not in markets:
            continue
        q = markets[key]
        # Deviating quote clocks may create artificial paired odds.
        timestamp = _clock(q["quote_retrieved_at"], "QUOTE_TIMESTAMP").isoformat()
        prices = pairs[key]
        for idx in (0, 1):
            from sportsedge.truth_gate import american_to_decimal
            no_vig = devig([american_to_decimal(p) for p in prices],
                           trigger_american=400, max_spread_pp=1.0)
            base_p, _ = _contract_prob(baseline, key, idx, spread if key == "spread" else total if key == "total" else None)
            raw_p, push_p = _contract_prob(residual, key, idx, spread if key == "spread" else total if key == "total" else None)
            conditional = float(no_vig[idx]) + (raw_p - base_p)
            if not 0.0 < conditional < 1.0:
                raise ResidualQuoteError("RESIDUAL_PROBABILITY_OUT_OF_RANGE")
            pwin = conditional * (1.0 - push_p)
            ploss = (1.0 - conditional) * (1.0 - push_p)
            p = prices[idx]
            edge = conditional - float(no_vig[idx])
            if key == "moneyline":
                selection = game["away"] if idx == 0 else game["home"]
                line = None
            elif key == "spread":
                selection = game["away"] if idx == 0 else game["home"]
                line = spread if idx == 0 else -spread
            else:
                selection = "Over" if idx == 0 else "Under"
                line = total
            rows.append({
                "market": key, "selection": selection, "line": line,
                "price_american": p, "market_no_vig_p": float(no_vig[idx]),
                "estimate_p": pwin, "conditional_fair_p": conditional,
                "push_p": push_p, "edge_probability_points": edge,
                "ev_per_dollar": pwin * (_decimal(p) - 1.0) - ploss,
                "fair_total": anchor["fair_total"], "fair_margin": anchor["fair_margin"],
                "joint_score_grid": True, "devig_method": DEVIG_METHOD,
                "quote_retrieved_at": timestamp,
                "status": "RESEARCH_ONLY", "eligible_as_bet": False,
                "forward_clv_status": "PENDING", "pricing_mode": "MARKET_ANCHORED_DELTA_V1",
            })
    return rows
