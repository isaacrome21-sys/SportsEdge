"""Bettor-facing rendering helpers for unified SportsEdge MLB card results.

This module is deliberately presentation-only.  It never changes model
probabilities, deployment state, Truth Gate decisions, or market tolerances.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from typing import Any, Iterable, Mapping

from .truth_gate import american_to_decimal

REQUIRED_MARKETS = (
    "MONEYLINE",
    "RUN_LINE",
    "TOTALS",
    "NRFI",
    "YRFI",
    "HITS",
    "TOTAL_BASES",
    "PITCHER_BB",
)


class BettorCardError(ValueError):
    pass


def _as_mapping(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        return result
    if is_dataclass(result):
        return asdict(result)
    raise BettorCardError("result must be mapping or dataclass")


def _fair_american(probability: float) -> int:
    p = float(probability)
    if not math.isfinite(p) or not 0 < p < 1:
        raise BettorCardError("probability must be finite in (0,1)")
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def _metrics(model_p: Any, american_odds: Any) -> dict[str, Any]:
    if model_p is None or american_odds is None:
        return {
            "implied_probability": None,
            "fair_odds": None,
            "edge": None,
            "ev_per_dollar": None,
        }
    p = float(model_p)
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise BettorCardError("invalid model_p")
    dec = american_to_decimal(float(american_odds))
    implied = 1.0 / dec
    ev = p * (dec - 1.0) - (1.0 - p)
    fair = None if p in (0.0, 1.0) else _fair_american(p)
    return {
        "implied_probability": implied,
        "fair_odds": fair,
        "edge": p - implied,
        "ev_per_dollar": ev,
    }


def _price_needed(model_p: Any, min_edge: float) -> int | None:
    if model_p is None:
        return None
    p = float(model_p)
    threshold_probability = p - float(min_edge)
    if not 0 < threshold_probability < 1:
        return None
    return _fair_american(threshold_probability)


def enrich_result(result: Any, *, min_edge: float = 0.0) -> dict[str, Any]:
    """Return a bettor-readable row without changing the underlying verdict.

    PASS rows with a valid Model_P become LEAN for presentation.  BLOCKED
    rows remain BLOCKED and can never be converted into a lean.
    """
    row = dict(_as_mapping(result))
    market = str(row.get("market") or "UNKNOWN")
    status = str(row.get("bet_status") or "BLOCKED")
    metrics = _metrics(row.get("model_p"), row.get("american_odds"))
    classification = status
    if status == "PASS" and row.get("model_p") is not None:
        classification = "LEAN"
    elif status not in {"OFFICIAL_BET", "BLOCKED", "PASS"}:
        classification = status

    row.update(metrics)
    row["classification"] = classification
    row["price_needed_for_official"] = (
        _price_needed(row.get("model_p"), min_edge)
        if classification == "LEAN" else None
    )
    row["market"] = market
    return row


def market_accounting(results: Iterable[Any]) -> dict[str, dict[str, int]]:
    """Account for every required market, including explicit zeroes."""
    accounting = {
        market: {"candidates": 0, "official": 0, "lean": 0, "pass": 0, "blocked": 0}
        for market in REQUIRED_MARKETS
    }
    for raw in results:
        row = _as_mapping(raw)
        market = str(row.get("market") or "UNKNOWN")
        if market not in accounting:
            continue
        accounting[market]["candidates"] += 1
        classification = str(row.get("classification") or row.get("bet_status") or "BLOCKED")
        if classification == "OFFICIAL_BET":
            accounting[market]["official"] += 1
        elif classification == "LEAN":
            accounting[market]["lean"] += 1
        elif classification == "PASS":
            accounting[market]["pass"] += 1
        else:
            accounting[market]["blocked"] += 1
    for market, counts in accounting.items():
        if counts["candidates"] != counts["official"] + counts["lean"] + counts["pass"] + counts["blocked"]:
            raise BettorCardError(f"market accounting mismatch: {market}")
    return accounting


def build_bettor_card(results: Iterable[Any], *, min_edge: float = 0.0) -> dict[str, Any]:
    rows = [enrich_result(r, min_edge=min_edge) for r in results]
    official = [r for r in rows if r["classification"] == "OFFICIAL_BET"]
    leans = [r for r in rows if r["classification"] == "LEAN"]

    # Strongest first.  Missing values sort to the bottom deterministically.
    official.sort(key=lambda r: (r.get("ev_per_dollar") is not None, r.get("ev_per_dollar") or -math.inf, r.get("edge") or -math.inf), reverse=True)
    leans.sort(key=lambda r: (r.get("edge") is not None, r.get("edge") or -math.inf, r.get("ev_per_dollar") or -math.inf), reverse=True)

    return {
        "official_bets_count": len(official),
        "best_official_bets": official,
        "best_leans_prices_to_watch": leans,
        "market_accounting": market_accounting(rows),
        "full_card": rows,
    }
