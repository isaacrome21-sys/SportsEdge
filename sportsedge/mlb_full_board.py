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

SCHEMA_VERSION = "MLB_FULL_BOARD_V3"
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



def pair_sides(market: str) -> tuple[str, str]:
    key = str(market or "").strip().upper()
    if key in {"NRFI", "YRFI", "PITCHER_RECORD_WIN"}:
        return ("YES", "NO")
    if key in SIDE_MARKETS:
        return ("HOME", "AWAY")
    if key == "FIRST_HOME_RUN":
        return ("YES", "FIELD")
    return ("OVER", "UNDER")


def _side_name(raw: Mapping[str, Any]) -> str:
    return str(raw.get("side") or raw.get("selection") or "").strip().upper()


def _group_key(market: str, raw: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        market,
        raw.get("game_id"),
        _entity(raw),
        raw.get("team_side"),
        raw.get("line"),
    )


def _complement_row(market: str, raw: Mapping[str, Any], side: str) -> dict[str, Any]:
    from sportsedge.both_side_pricing import complement_model_p

    opposite = raw.get("opposite_odds")
    model_p = complement_model_p(raw, market=market) if opposite is not None else None
    if opposite is None:
        reason = "COMPLEMENT_SIDE_NOT_QUOTED"
        presentation = "BLOCKED"
    elif model_p is None:
        reason = "COMPLEMENT_PRICE_ONLY"
        presentation = "BLOCKED"
    else:
        reason = "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
        presentation = "LEAN"
    return {
        "lane": family_for(market),
        "market": market,
        "game_id": raw.get("game_id"),
        "entity_id": _entity(raw),
        "team_side": raw.get("team_side"),
        "side": side,
        "line": raw.get("line"),
        "american_odds": opposite,
        "model_p": model_p,
        "research_only": True,
        "official_eligible": False,
        "presentation": presentation,
        "reason": reason,
    }


def emit_all_props_side_totals(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Emit both sides of every quoted prop, side, and total, plus catalog blockers.

    A complement is priced only when the opposite quote was supplied and the
    other-side probability is already determined by the quoted row.
    """
    return build_mlb_full_board(rows, catalog=catalog)

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
        side = _side_name(raw)
        emitted.append({
            "lane": family_for(market),
            "market": market,
            "game_id": raw.get("game_id"),
            "entity_id": _entity(raw),
            "team_side": raw.get("team_side"),
            "side": side or None,
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds") or raw.get("price_american"),
            "model_p": model_p,
            "research_only": True,
            "official_eligible": False,
            "presentation": _presentation(raw, model_p),
            "reason": raw.get("reason") or raw.get("card_reason") or raw.get("score_reason") or "RESEARCH_ROW",
        })
        left, right = pair_sides(market)
        present = {
            _side_name(item)
            for item in rows
            if isinstance(item, Mapping)
            and str(item.get("market") or item.get("engine_market") or "").strip().upper() == market
            and _group_key(market, item) == _group_key(market, raw)
        }
        for missing in (left, right):
            if missing in present:
                continue
            if side == missing:
                continue
            emitted.append(_complement_row(market, raw, missing))
            present.add(missing)
    for market in markets:
        if market in seen:
            continue
        left, right = pair_sides(market)
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
    summary = {
        "catalog_markets": len(markets),
        "priced_rows": sum(1 for row in emitted if row["model_p"] is not None),
        "priced_complement_rows": sum(1 for row in emitted if row.get("reason") == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"),
        "blocked_family_rows": sum(1 for row in emitted if row["reason"] == "NO_QUOTE_OR_ENGINE_ROW"),
        "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
        "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
        "prop_rows": sum(1 for row in emitted if row["lane"] == "PROP"),
        "both_sides": all(
            {str(row.get("side") or "") for row in emitted if row["market"] == market} >= set(pair_sides(market))
            for market in markets
        ),
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
