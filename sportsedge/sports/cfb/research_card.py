"""Unified research-card view for CFB game markets and player props.

The CFB game lane and the frozen player-prop candidate lane have different
production authority. This module combines their outputs for one research card
without changing either underlying authority. Rows may be displayed as LEAN
only; nothing emitted here is OFFICIAL or promotion-eligible.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

GAME_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL"})
SCHEMA_VERSION = "CFB_FULL_RESEARCH_CARD_V1"


class CFBResearchCardError(ValueError):
    pass


def _unwrap(payload: Mapping[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CFBResearchCardError(code)
    nested = payload.get("report")
    return dict(nested) if isinstance(nested, Mapping) else dict(payload)


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) and 0.0 <= out <= 1.0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) else None


def _game_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    market = str(raw.get("market") or "").strip().upper()
    if market not in GAME_MARKETS:
        return None
    model_p = _probability(raw.get("model_p"))
    reason = str(raw.get("reason") or "")
    fresh = "STALE" not in reason.upper()
    lean = model_p is not None and fresh
    return {
        "lane": "GAME",
        "game_id": str(raw.get("game_id") or ""),
        "market": market,
        "side": str(raw.get("side") or ""),
        "selection": raw.get("selection"),
        "line": _number(raw.get("line")),
        "american_odds": _number(raw.get("american_odds")),
        "model_p": model_p,
        "fair_market_p": _probability(raw.get("fair_market_p")),
        "edge": _number(raw.get("edge")),
        "ev_per_dollar": _number(raw.get("ev_per_dollar")),
        "display_status": "LEAN" if lean else "BLOCKED",
        "underlying_bet_status": str(raw.get("bet_status") or "BLOCKED"),
        "official_eligible": False,
        "reason": (
            "CFB_RESEARCH_CARD_GAME_LEAN_OFFICIAL_GATE_UNCHANGED"
            if lean else (reason or "CFB_RESEARCH_CARD_GAME_BLOCKED")
        ),
        "distribution_sha256": raw.get("distribution_sha256"),
    }


def _prop_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    model_p = _probability(raw.get("model_p"))
    fresh = raw.get("quote_fresh") is True
    candidate = raw.get("model_candidate_status") == "READY"
    actionable_research = model_p is not None and fresh and candidate
    if model_p is None and not raw.get("provider_market"):
        return None
    return {
        "lane": "PLAYER_PROP",
        "game_id": str(raw.get("game_id") or ""),
        "market": str(raw.get("provider_market") or raw.get("market") or ""),
        "stat": raw.get("market"),
        "player_id": raw.get("player_id"),
        "player_name": raw.get("player_name"),
        "side": str(raw.get("side") or raw.get("primary_side") or ""),
        "line": _number(raw.get("line")),
        "american_odds": _number(raw.get("american_odds") if raw.get("american_odds") is not None else raw.get("primary_price")),
        "model_p": model_p,
        "fair_market_p": _probability(raw.get("fair_market_p")),
        "edge": _number(raw.get("edge")),
        "ev_per_dollar": _number(raw.get("ev_per_dollar")),
        "display_status": "LEAN" if actionable_research else "BLOCKED",
        "underlying_bet_status": "BLOCKED",
        "official_eligible": False,
        "reason": (
            "CFB_PROP_RESEARCH_LEAN_INDEPENDENT_VALIDATION_REQUIRED"
            if actionable_research else str(raw.get("reason") or "CFB_PROP_RESEARCH_BLOCKED")
        ),
        "distribution_sha256": raw.get("distribution_sha256"),
    }


def assemble_cfb_research_card(
    *,
    game_payload: Mapping[str, Any],
    prop_payload: Mapping[str, Any],
) -> dict[str, Any]:
    game = _unwrap(game_payload, code="CFB_RESEARCH_CARD_GAME_PAYLOAD_INVALID")
    props = _unwrap(prop_payload, code="CFB_RESEARCH_CARD_PROP_PAYLOAD_INVALID")
    game_rows = [
        row for raw in game.get("results", [])
        if isinstance(raw, Mapping) and (row := _game_row(raw)) is not None
    ]
    prop_rows = [
        row for raw in props.get("results", [])
        if isinstance(raw, Mapping) and (row := _prop_row(raw)) is not None
    ]
    rows = sorted(
        [*game_rows, *prop_rows],
        key=lambda row: (
            str(row.get("game_id") or ""),
            str(row.get("lane") or ""),
            str(row.get("market") or ""),
            str(row.get("player_name") or ""),
            str(row.get("side") or ""),
        ),
    )
    leans = [row for row in rows if row["display_status"] == "LEAN"]
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "CFB",
        "run_status": "RESEARCH_LEANS_AVAILABLE" if leans else "RESEARCH_BLOCKED_NO_LEANS",
        "rows": rows,
        "summary": {
            "game_rows": len(game_rows),
            "prop_rows": len(prop_rows),
            "lean_rows": len(leans),
            "official_bets": 0,
            "markets_seen": sorted({str(row["market"]) for row in rows}),
        },
        "governance": {
            "research_only": True,
            "production_authority_changed": False,
            "prop_engine_surface_changed": False,
            "truth_gate_changed": False,
            "promotion_authority": False,
            "official_authority": False,
            "staking_authority": False,
        },
    }


__all__ = ["CFBResearchCardError", "SCHEMA_VERSION", "assemble_cfb_research_card"]
