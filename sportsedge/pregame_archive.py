"""Persist the last valid pregame SportsEdge evidence for every MLB game.

The archive is display/evidence state, never a mechanism for creating new bets
on started games. Current runs may update a game's archive only while that game
is still confirmed pregame. Once first pitch passes, the stored pregame snapshot
is immutable for the rest of the slate day.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .mlb_source import parse_game_start

SCHEMA_VERSION = 1


def _rows(payload: Mapping[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = (payload or {}).get(key)
    if not isinstance(value, list):
        return []
    return [dict(x) for x in value if isinstance(x, Mapping)]


def _generated(payload: Mapping[str, Any] | None) -> str | None:
    value = (payload or {}).get("generated_at_utc")
    return str(value) if value else None


def update_pregame_archive(
    *,
    schedule: Iterable[Any],
    now: datetime,
    prior: Mapping[str, Any] | None = None,
    card_payload: Mapping[str, Any] | None = None,
    game_odds_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = now.astimezone(timezone.utc)
    prior = prior if isinstance(prior, Mapping) else {}
    prior_games = prior.get("games") if isinstance(prior.get("games"), Mapping) else {}
    out_games = {str(k): dict(v) for k, v in prior_games.items() if isinstance(v, Mapping)}

    card_rows = _rows(card_payload, "results")
    quote_rows = _rows(game_odds_payload, "quotes")
    card_by_game: dict[str, list[dict[str, Any]]] = {}
    quote_by_game: dict[str, list[dict[str, Any]]] = {}
    for row in card_rows:
        card_by_game.setdefault(str(row.get("game_id") or ""), []).append(row)
    for row in quote_rows:
        quote_by_game.setdefault(str(row.get("game_id") or ""), []).append(row)

    for snap in schedule:
        gid = str(getattr(snap, "game_pk"))
        status = str(getattr(snap, "status", ""))
        try:
            start = parse_game_start(getattr(snap, "game_date"))
        except Exception:
            continue
        pregame = status == "Preview" and current < start
        if not pregame:
            continue
        # Only pregame runs can mutate the archive for this game.
        rows = card_by_game.get(gid, [])
        quotes = quote_by_game.get(gid, [])
        if not rows and not quotes:
            continue
        out_games[gid] = {
            "game_id": gid,
            "game_start_utc": start.isoformat(),
            "away_team": str(getattr(snap, "away_name", "") or ""),
            "home_team": str(getattr(snap, "home_name", "") or ""),
            "archived_at_utc": current.isoformat(),
            "card_generated_at_utc": _generated(card_payload),
            "game_odds_generated_at_utc": _generated(game_odds_payload),
            "card_rows": rows,
            "game_quotes": quotes,
            "archive_kind": "LAST_VALID_PREGAME_EVIDENCE",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at_utc": current.isoformat(),
        "games": out_games,
        "policy": "pregame_only_updates_started_games_immutable",
    }


def archived_game(prior: Mapping[str, Any] | None, game_id: str) -> dict[str, Any] | None:
    if not isinstance(prior, Mapping):
        return None
    games = prior.get("games")
    if not isinstance(games, Mapping):
        return None
    value = games.get(str(game_id))
    return dict(value) if isinstance(value, Mapping) else None
