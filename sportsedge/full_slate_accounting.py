"""Per-game, per-market accounting for a full MLB slate.

This module is intentionally model-agnostic. It prevents a Full Model run made
late in the day from silently shrinking to only games that are still pregame.
Every scheduled game remains visible in evidence, while started/final games are
explicitly non-actionable unless a preserved pregame evaluation already exists.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .market_coverage import REQUIRED_MARKET_FAMILIES
from .mlb_source import parse_game_start


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, Mapping)]


def _game_id(row: Mapping[str, Any]) -> str:
    return str(row.get("game_id") or row.get("game_pk") or "")


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market") or "UNKNOWN").upper()


def _status(snapshot: Any, *, now: datetime) -> tuple[str, bool, str]:
    status = str(getattr(snapshot, "status", "UNKNOWN") or "UNKNOWN")
    try:
        start = parse_game_start(getattr(snapshot, "game_date"))
    except Exception:
        start = None
    if status == "Preview" and start is not None and now < start:
        return "PREGAME", True, "GAME_PREGAME"
    if status in {"Final", "Game Over", "Completed Early"}:
        return "FINAL", False, "GAME_FINAL"
    if start is not None and now >= start:
        return "STARTED", False, "GAME_ALREADY_STARTED"
    return status.upper().replace(" ", "_"), False, "GAME_NOT_CONFIRMED_PREGAME"


def build_full_slate_accounting(
    *,
    schedule: Iterable[Any],
    now: datetime,
    card_payload: Mapping[str, Any] | None = None,
    game_odds_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = now.astimezone(timezone.utc)
    card_rows = _rows((card_payload or {}).get("results"))
    game_quotes = _rows((game_odds_payload or {}).get("quotes"))

    card_by_game: dict[str, list[Mapping[str, Any]]] = {}
    quote_by_game: dict[str, list[Mapping[str, Any]]] = {}
    for row in card_rows:
        card_by_game.setdefault(_game_id(row), []).append(row)
    for row in game_quotes:
        quote_by_game.setdefault(_game_id(row), []).append(row)

    games: list[dict[str, Any]] = []
    for snap in schedule:
        gid = str(getattr(snap, "game_pk"))
        state, actionable, reason = _status(snap, now=current)
        card = card_by_game.get(gid, [])
        quotes = quote_by_game.get(gid, [])
        card_market_counts = Counter(_market(x) for x in card)
        quote_market_counts = Counter(_market(x) for x in quotes)
        family_rows: list[dict[str, Any]] = []
        for family in REQUIRED_MARKET_FAMILIES:
            rows = [x for x in card if _market(x) == family]
            statuses = Counter(str(x.get("bet_status") or "UNKNOWN") for x in rows)
            if rows:
                if statuses.get("OFFICIAL_BET", 0):
                    fam_state = "ACTIONABLE" if actionable else "PRESERVED_PREGAME_RESULT"
                elif statuses.get("BLOCKED", 0) == len(rows):
                    fam_state = "BLOCKED"
                else:
                    fam_state = "EVALUATED"
            elif quote_market_counts.get(family, 0):
                fam_state = "ACQUIRED_NO_MODEL"
            else:
                fam_state = "NOT_FOUND" if actionable else "NOT_BETTABLE_GAME_STATE"
            family_rows.append({
                "market_family": family,
                "state": fam_state,
                "card_rows": int(card_market_counts.get(family, 0)),
                "quote_rows": int(quote_market_counts.get(family, 0)),
                "bet_status_counts": dict(statuses),
            })
        games.append({
            "game_id": gid,
            "away_team": str(getattr(snap, "away_name", "") or ""),
            "home_team": str(getattr(snap, "home_name", "") or ""),
            "game_state": state,
            "new_bets_allowed": actionable,
            "reason": reason,
            "market_families": family_rows,
        })

    return {
        "generated_at_utc": current.isoformat(),
        "scheduled_games": len(games),
        "games": games,
        "complete_game_accounting": len(games) > 0,
        "required_market_families": list(REQUIRED_MARKET_FAMILIES),
        "policy": "all_scheduled_games_visible_never_silent_late_slate_only",
    }
