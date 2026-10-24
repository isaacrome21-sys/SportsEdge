"""Honest, market-neutral matchup explanations for SportsEdge research cards.

This is presentation only. Facts must already be on a priced result with
explicit source metadata. It never supplies Model_P, changes a price, or
grants PLAY authority. It applies to every sport and every market string.
"""
from __future__ import annotations

from math import ceil, isfinite
from typing import Any, Mapping

from sportsedge.quote_freshness import is_fresh


def _probability(row: Mapping[str, Any]) -> float | None:
    independent = row.get("independent_projection")
    if isinstance(independent, Mapping):
        data = independent
    else:
        data = row
    for key in ("estimate_p", "model_probability"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isfinite(value) and 0 < value < 1:
                return float(value)
    return None


def _american(odds: float) -> int | None:
    if odds >= 2:
        return ceil(100 * (odds - 1))
    if odds > 1:
        return ceil(-100 / (odds - 1))
    return None


def _line_price(row: Mapping[str, Any]) -> int | None:
    for key in ("odds_american", "dk_odds", "odds"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isfinite(value) and (value <= -100 or value >= 100):
                return int(value)
    return None


def handicap_explanation(
    row: Mapping[str, Any], *,
    sport: str | None = None,
    market: str | None = None,
    evidence: list[Mapping[str, Any]] | None = None,
    straight_cap: int = -165,
) -> dict[str, Any]:
    """Describe measurable supplied factors without claiming verification.

    Factor records are a transport seam for source collectors, not
    authorization. Every factor needs an explicit name, value, source, and
    direction. Future admission may independently attest those sources.
    """
    sport = str(sport or row.get("sport") or "UNKNOWN").upper()
    market = str(market or row.get("market") or "UNKNOWN").upper()
    selection = str(row.get("selection") or row.get("side") or "UNKNOWN").upper()
    observed = []
    missing = []
    if evidence is None:
        evidence = row.get("handicap_factors") or []
    if not isinstance(evidence, list):
        evidence = []
        missing.append("HANDICAP_FACTORS_MALFORMED")
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        value = item.get("value")
        source = item.get("source")
        direction = str(item.get("direction") or "").upper()
        if (not isinstance(name, str) or not name.strip()
                or value is None or isinstance(value, bool)
                or not isinstance(source, str) or not source.strip()
                or direction not in {"SUPPORTS", "OPPOSES", "NEUTRAL"}):
            missing.append("FACTOR_INCOMPLETE")
            continue
        observed.append({
            "name": name.strip()[:80],
            "value": str(value)[:80],
            "source": source.strip()[:100],
            "direction": direction,
            "evidence_status": "REPORTED_NOT_INDEPENDENTLY_ATTESTED",
        })
    if not observed:
        missing.append("NO_SOURCE_BACKED_MATCHUP_FACTORS")

    p = _probability(row)
    quoted = _line_price(row)
    # Market-anchored projections cannot independently establish value.
    prov = row.get("pricing_provenance")
    anchored = (
        row.get("pricing_lane") == "LANE_B_ANCHORED"
        or isinstance(prov, Mapping) and prov.get("lane") == "MARKET_ANCHORED"
    )
    quote_freshness = row.get("quote_freshness")
    quote_fresh = is_fresh(quote_freshness)
    if quote_freshness is None:
        quote_fresh = row.get("quote_status") == "RECENT_CAPTURED_QUOTE"
    estimate = None
    if p is not None and quoted is not None and not anchored:
        decimal = 1 + (100 / -quoted if quoted < 0 else quoted / 100)
        estimate = {
            "research_model_probability": round(p, 6),
            "raw_implied_probability": round(1 / decimal, 6),
            "research_ev_per_dollar": round(p * decimal - 1, 6),
            "research_playable_to_positive_ev": max(straight_cap, _american(1 / p)),
            "straight_cap": straight_cap,
            "no_vig_implied_probability": None,
            "authority": "RESEARCH_MATH_ONLY_NOT_A_VERIFIED_EDGE",
        }
    if p is None:
        missing.append("NO_INDEPENDENT_MODEL_PROBABILITY")
    if quoted is None:
        missing.append("NO_VALID_BOOK_PRICE")
    if anchored:
        missing.append("MARKET_ANCHORED_PROJECTION_CANNOT_PROVE_EDGE")
    if not quote_fresh:
        missing.append("NO_VERIFIED_FRESH_BOOK_QUOTE")
    return {
        "schema": "SPORTSEDGE_HANDICAP_EXPLANATION_V1",
        "sport": sport, "market": market, "selection": selection,
        "evidence": observed,
        "supporting_factors": [x for x in observed if x["direction"] == "SUPPORTS"],
        "opposing_factors": [x for x in observed if x["direction"] == "OPPOSES"],
        "missing": sorted(set(missing)),
        "research_price_screen": estimate,
        "verified_play": False,
        "release_status": "RESEARCH_ONLY_NO_PROMOTION_AUTHORITY",
    }
