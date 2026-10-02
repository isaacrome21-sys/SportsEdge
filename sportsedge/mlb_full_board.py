"""Complete MLB side, total, and prop presentation board.

This module does not create probabilities, change Model_P, or open a market.
It keeps every catalog family visible: a missing quote or engine row is an
explicit blocker, never a silent omission. Evidence completion stays separate
from this engineering board.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .generic_market_engine import BINARY_MARKETS, COUNT_MARKETS, GAME_MARKETS

SCHEMA_VERSION = "MLB_FULL_BOARD_V1"
DEFAULT_SURFACE = Path("config/mlb_market_surface.json")

SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE"})
TOTAL_MARKETS = frozenset({
    "TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS", "NRFI", "YRFI",
})
PITCHER_MARKETS = frozenset({
    "PITCHER_K", "PITCHER_HITS_ALLOWED", "PITCHER_BB", "PITCHER_ER", "PITCHER_OUTS",
    "PITCHER_HITS_WALKS_ER", "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER", "PITCHER_RECORD_WIN",
})


class MLBFullBoardError(ValueError):
    pass


def catalog_markets(surface_path: str | Path = DEFAULT_SURFACE) -> tuple[str, ...]:
    payload = json.loads(Path(surface_path).read_text(encoding="utf-8"))
    rows = payload.get("markets")
    if not isinstance(rows, list) or not rows:
        raise MLBFullBoardError("MLB_FULL_BOARD_SURFACE_INVALID")
    names = []
    for row in rows:
        if not isinstance(row, Mapping) or not str(row.get("market") or "").strip():
            raise MLBFullBoardError("MLB_FULL_BOARD_SURFACE_MARKET_INVALID")
        names.append(str(row["market"]))
    if len(names) != len(set(names)):
        raise MLBFullBoardError("MLB_FULL_BOARD_SURFACE_DUPLICATE")
    return tuple(names)


def _family(market: str) -> str:
    if market in SIDE_MARKETS:
        return "SIDE"
    if market in TOTAL_MARKETS:
        return "TOTAL"
    if market in PITCHER_MARKETS or market in BINARY_MARKETS and market != "FIRST_HOME_RUN":
        return "PITCHER_PROP"
    if market == "FIRST_HOME_RUN":
        return "BATTER_PROP"
    if market in COUNT_MARKETS or market not in GAME_MARKETS:
        return "BATTER_PROP"
    return "OTHER"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _presentation(row: Mapping[str, Any]) -> str:
    status = str(row.get("bet_status") or row.get("card_status") or row.get("status") or "").upper()
    if status in {"BLOCKED", "NO_MODEL", "PASS"}:
        return status if status != "PASS" else "PASS"
    model_p = _number(row.get("model_p") if row.get("model_p") is not None else row.get("research_p"))
    if model_p is None:
        return "NO_MODEL"
    if status in {"ACTIONABLE", "PRIMARY_RESEARCH_PLAY"}:
        return "LEAN"
    return "LEAN"


def build_mlb_full_board(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Emit every side, total, and prop family without collapsing the board."""
    markets = tuple(catalog) if catalog is not None else catalog_markets()
    if not markets:
        raise MLBFullBoardError("MLB_FULL_BOARD_CATALOG_REQUIRED")
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MLBFullBoardError("MLB_FULL_BOARD_ROW_INVALID")
        market = str(raw.get("market") or raw.get("engine_market") or "").upper()
        if not market:
            raise MLBFullBoardError("MLB_FULL_BOARD_MARKET_REQUIRED")
        seen.add(market)
        model_p = raw.get("model_p") if raw.get("model_p") is not None else raw.get("research_p")
        emitted.append({
            "lane": _family(market),
            "market": market,
            "game_id": raw.get("game_id"),
            "entity_id": raw.get("entity_id") or raw.get("pitcher_name") or raw.get("team_side"),
            "side": raw.get("side"),
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds"),
            "model_p": model_p,
            "research_only": True,
            "official_eligible": False,
            "presentation": _presentation(raw),
            "reason": raw.get("reason") or raw.get("card_reason") or "RESEARCH_ROW",
        })
    for market in markets:
        if market in seen:
            continue
        emitted.append({
            "lane": _family(market),
            "market": market,
            "game_id": None,
            "entity_id": None,
            "side": None,
            "line": None,
            "american_odds": None,
            "model_p": None,
            "research_only": True,
            "official_eligible": False,
            "presentation": "BLOCKED",
            "reason": "NO_QUOTE_OR_ENGINE_ROW",
        })
    summary = {
        "catalog_markets": len(markets),
        "priced_rows": sum(1 for row in emitted if row["model_p"] is not None),
        "blocked_family_rows": sum(1 for row in emitted if row["reason"] == "NO_QUOTE_OR_ENGINE_ROW"),
        "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
        "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
        "prop_rows": sum(1 for row in emitted if row["lane"] in {"BATTER_PROP", "PITCHER_PROP"}),
        "official_bets": 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "PRESENTATION_ONLY",
        "model_p_authority": False,
        "truth_gate_authority": False,
        "official_authority": False,
        "summary": summary,
        "rows": emitted,
    }
