"""Assemble a practical same-day CFB research card without changing authority.

Priority:
1. If a hash-valid research game-model candidate report exists, use those numeric
   ML/spread/total/team-total rows as LEANs.
2. Otherwise use the exact-line cross-book PAPER market board for ML/spread/total.
3. Add any frozen-artifact CFB prop research candidates.

PAPER market context never becomes Model_P. Research model rows never become
OFFICIAL here.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .research_card import assemble_cfb_research_card

SCHEMA_VERSION = "CFB_TODAY_RESEARCH_CARD_V1"


class CFBTodayResearchCardError(ValueError):
    pass


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _paper_rows(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        market = str(raw.get("market") or "").strip().upper()
        if market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            continue
        out.append({
            "lane": "GAME_MARKET_CONTEXT",
            "game_id": str(raw.get("game_id") or ""),
            "market": market,
            "side": str(raw.get("side") or ""),
            "selection": raw.get("side"),
            "line": _num(raw.get("line")),
            "american_odds": _num(raw.get("draftkings_odds")),
            "model_p": None,
            "fair_market_p": _num(raw.get("market_consensus_no_vig_p")),
            "edge": _num(raw.get("market_consensus_edge")),
            "ev_per_dollar": _num(raw.get("market_consensus_ev_per_dollar")),
            "display_status": "PAPER",
            "underlying_bet_status": "BLOCKED",
            "official_eligible": False,
            "reason": "CFB_MARKET_CONSENSUS_NOT_MODEL_P",
            "distribution_sha256": None,
            "peer_books_used": raw.get("peer_books_used"),
            "line_identity_rule": raw.get("line_identity_rule"),
        })
    return out


def assemble_cfb_today_research_card(
    *,
    game_model_payload: Mapping[str, Any] | None = None,
    paper_market_payload: Mapping[str, Any] | None = None,
    prop_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    prop_source = prop_payload if isinstance(prop_payload, Mapping) else {"results": []}
    game_source = game_model_payload if isinstance(game_model_payload, Mapping) else {"results": []}
    base = assemble_cfb_research_card(
        game_payload=game_source,
        prop_payload=prop_source,
    )
    numeric_game_rows = [row for row in base["rows"] if row.get("lane") == "GAME"]
    prop_rows = [row for row in base["rows"] if row.get("lane") == "PLAYER_PROP"]

    if numeric_game_rows:
        game_rows = numeric_game_rows
        game_lane = "GAME_MODEL"
    else:
        game_rows = _paper_rows(paper_market_payload)
        game_lane = "MARKET_CONSENSUS" if game_rows else "MISSING"

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
    lean_rows = sum(row.get("display_status") == "LEAN" for row in rows)
    paper_rows = sum(row.get("display_status") == "PAPER" for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "CFB",
        "run_status": (
            "RESEARCH_LEANS_AVAILABLE"
            if lean_rows
            else ("PAPER_CONTEXT_AVAILABLE" if paper_rows else "RESEARCH_BLOCKED_NO_ROWS")
        ),
        "game_lane": game_lane,
        "prop_lane": "PLAYER_PROP_MODEL" if prop_rows else "MISSING",
        "rows": rows,
        "summary": {
            "game_rows": len(game_rows),
            "prop_rows": len(prop_rows),
            "lean_rows": lean_rows,
            "paper_rows": paper_rows,
            "official_bets": 0,
            "markets_seen": sorted({str(row.get("market") or "") for row in rows}),
        },
        "governance": {
            "research_only": True,
            "paper_market_context_can_create_model_p": False,
            "production_authority_changed": False,
            "prop_engine_surface_changed": False,
            "truth_gate_changed": False,
            "promotion_authority": False,
            "official_authority": False,
            "staking_authority": False,
        },
    }


__all__ = [
    "CFBTodayResearchCardError",
    "SCHEMA_VERSION",
    "assemble_cfb_today_research_card",
]
