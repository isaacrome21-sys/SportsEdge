"""Complete MLB side, total, and prop presentation board.

This module does not create probabilities, change Model_P, or open a market.
Every canonical catalog family stays visible. A missing quote or engine row is
an explicit blocker, never a silent omission. Evidence completion stays separate
from this engineering board.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "MLB_FULL_BOARD_V2"
DEFAULT_CATALOG = Path("config/mlb_market_catalog.json")

SIDE_MARKETS = frozenset({
    "MONEYLINE", "RUN_LINE", "F5_MONEYLINE", "F5_RUN_LINE",
})
TOTAL_MARKETS = frozenset({
    "TOTALS", "TEAM_TOTALS", "F5_TOTALS", "F5_TEAM_TOTALS", "NRFI", "YRFI",
})
_GROUPS = (
    "game_markets",
    "batter_markets",
    "pitcher_markets",
    "separate_protocol_markets",
    "binary_markets_not_coerced",
    "period_markets_not_coerced",
)


class MLBFullBoardError(ValueError):
    pass


def catalog_markets(catalog_path: str | Path = DEFAULT_CATALOG) -> tuple[str, ...]:
    payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    names: list[str] = []
    for group in _GROUPS:
        rows = payload.get(group)
        if not isinstance(rows, list):
            raise MLBFullBoardError(f"MLB_FULL_BOARD_CATALOG_GROUP_INVALID:{group}")
        for raw in rows:
            market = str(raw or "").strip().upper()
            if not market:
                raise MLBFullBoardError("MLB_FULL_BOARD_CATALOG_MARKET_INVALID")
            if market not in names:
                names.append(market)
    if len(names) < 38:
        raise MLBFullBoardError("MLB_FULL_BOARD_CATALOG_INCOMPLETE")
    return tuple(names)


def family_for(market: str) -> str:
    key = str(market or "").strip().upper()
    if key in SIDE_MARKETS:
        return "SIDE"
    if key in TOTAL_MARKETS:
        return "TOTAL"
    return "PROP"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _presentation(row: Mapping[str, Any], model_p: float | None) -> str:
    status = str(
        row.get("bet_status") or row.get("scored_status") or row.get("card_status") or row.get("status") or ""
    ).upper()
    if status in {"BLOCKED", "NO_MODEL", "PASS"}:
        return status
    if model_p is None:
        return "NO_MODEL"
    return "LEAN"


def _entity(row: Mapping[str, Any]) -> Any:
    return (
        row.get("entity_id")
        or row.get("player_id")
        or row.get("pitcher_name")
        or row.get("batter_name")
        or row.get("team_side")
        or row.get("selection")
    )


def build_mlb_full_board(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Emit every side, total, and prop family without collapsing the board."""
    markets = tuple(str(market).upper() for market in catalog) if catalog is not None else catalog_markets()
    if not markets:
        raise MLBFullBoardError("MLB_FULL_BOARD_CATALOG_REQUIRED")
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MLBFullBoardError("MLB_FULL_BOARD_ROW_INVALID")
        market = str(raw.get("market") or raw.get("engine_market") or "").strip().upper()
        if not market or market == "UNKNOWN":
            continue
        seen.add(market)
        model_p = _number(raw.get("model_p") if raw.get("model_p") is not None else raw.get("research_p"))
        emitted.append({
            "lane": family_for(market),
            "market": market,
            "game_id": raw.get("game_id"),
            "entity_id": _entity(raw),
            "side": raw.get("side") or raw.get("selection"),
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds") or raw.get("price_american"),
            "model_p": model_p,
            "research_only": True,
            "official_eligible": False,
            "presentation": _presentation(raw, model_p),
            "reason": raw.get("reason") or raw.get("card_reason") or raw.get("score_reason") or "RESEARCH_ROW",
        })
    for market in markets:
        if market in seen:
            continue
        emitted.append({
            "lane": family_for(market),
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
        "prop_rows": sum(1 for row in emitted if row["lane"] == "PROP"),
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


_SIDE_PAIRS = {
    "MONEYLINE": ("HOME", "AWAY"),
    "RUN_LINE": ("HOME", "AWAY"),
    "F5_MONEYLINE": ("HOME", "AWAY"),
    "F5_RUN_LINE": ("HOME", "AWAY"),
}
_TOTAL_PAIRS = {
    "TOTALS": ("OVER", "UNDER"),
    "TEAM_TOTALS": ("OVER", "UNDER"),
    "F5_TOTALS": ("OVER", "UNDER"),
    "F5_TEAM_TOTALS": ("OVER", "UNDER"),
    "NRFI": ("YES", "NO"),
    "YRFI": ("YES", "NO"),
}


def _pair_sides(market: str) -> tuple[str, str]:
    key = str(market or "").strip().upper()
    if key in _SIDE_PAIRS:
        return _SIDE_PAIRS[key]
    if key in _TOTAL_PAIRS:
        return _TOTAL_PAIRS[key]
    return ("OVER", "UNDER")


def _group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    line = row.get("line")
    line_key = "" if line is None else str(line)
    return (
        str(row.get("market") or "").strip().upper(),
        str(row.get("game_id") or ""),
        str(row.get("entity_id") or row.get("team_side") or ""),
        line_key,
        str(row.get("team_side") or ""),
    )


def emit_all_props_side_totals(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog_path: str | Path = DEFAULT_CATALOG,
) -> dict[str, Any]:
    """Emit both sides of every quoted prop, side, and total.

    A quoted side keeps its model probability. The missing complement is explicit
    and research-only. Catalog families with no quote stay blockers. This does
    not create Model_P, Truth Gate, or official authority.
    """
    markets = catalog_markets(catalog_path)
    grouped: dict[tuple[str, str, str, str, str], dict[str, Mapping[str, Any]]] = {}
    order: list[tuple[str, str, str, str, str]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MLBFullBoardError("MLB_ALL_SIDES_ROW_INVALID")
        market = str(raw.get("market") or raw.get("engine_market") or "").strip().upper()
        if not market or market == "UNKNOWN":
            continue
        key = _group_key({**dict(raw), "market": market})
        side = str(raw.get("side") or raw.get("selection") or "").strip().upper()
        if key not in grouped:
            grouped[key] = {}
            order.append(key)
        if side:
            grouped[key][side] = raw
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in order:
        market = key[0]
        seen.add(market)
        present = grouped[key]
        left, right = _pair_sides(market)
        for side in (left, right):
            raw = present.get(side)
            if raw is None:
                donor = next(iter(present.values()))
                model_p = _number(donor.get("model_p") if donor.get("model_p") is not None else donor.get("research_p"))
                complement = None if model_p is None else max(0.0, 1.0 - model_p)
                emitted.append({
                    "lane": family_for(market),
                    "market": market,
                    "game_id": donor.get("game_id"),
                    "entity_id": _entity(donor),
                    "team_side": donor.get("team_side"),
                    "side": side,
                    "line": donor.get("line"),
                    "american_odds": donor.get("opposite_odds"),
                    "model_p": complement,
                    "research_only": True,
                    "official_eligible": False,
                    "presentation": "NO_QUOTE" if donor.get("opposite_odds") is None else "COMPLEMENT",
                    "reason": "COMPLEMENT_SIDE_NOT_QUOTED",
                })
                continue
            model_p = _number(raw.get("model_p") if raw.get("model_p") is not None else raw.get("research_p"))
            emitted.append({
                "lane": family_for(market),
                "market": market,
                "game_id": raw.get("game_id"),
                "entity_id": _entity(raw),
                "team_side": raw.get("team_side"),
                "side": side,
                "line": raw.get("line"),
                "american_odds": raw.get("american_odds") or raw.get("price_american"),
                "model_p": model_p,
                "research_only": True,
                "official_eligible": False,
                "presentation": _presentation(raw, model_p),
                "reason": raw.get("reason") or raw.get("card_reason") or raw.get("score_reason") or "RESEARCH_ROW",
            })
    for market in markets:
        if market in seen:
            continue
        left, right = _pair_sides(market)
        for side in (left, right):
            emitted.append({
                "lane": family_for(market),
                "market": market,
                "game_id": None,
                "entity_id": None,
                "team_side": None,
                "side": side,
                "line": None,
                "american_odds": None,
                "model_p": None,
                "research_only": True,
                "official_eligible": False,
                "presentation": "BLOCKED",
                "reason": "NO_QUOTE_OR_ENGINE_ROW",
            })
    return {
        "schema_version": "MLB_ALL_PROPS_SIDE_TOTALS_V1",
        "authority": "PRESENTATION_ONLY",
        "model_p_authority": False,
        "truth_gate_authority": False,
        "official_authority": False,
        "summary": {
            "catalog_markets": len(markets),
            "quoted_groups": len(order),
            "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
            "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
            "prop_rows": sum(1 for row in emitted if row["lane"] == "PROP"),
            "both_sides": all(
                {row["side"] for row in emitted if row["market"] == market} >= set(_pair_sides(market))
                for market in markets
            ),
            "official_bets": 0,
        },
        "rows": emitted,
    }
