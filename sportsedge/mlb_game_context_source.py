"""MLB gameday context acquisition from StatsAPI live game feeds.

Provides weather, confirmed batting order, home-plate umpire, and starting catcher
context with explicit source timestamps for downstream MLB models. This module is
an acquisition/parser layer only; model-specific weighting remains separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
SOURCE = "MLB_STATSAPI_LIVE_FEED"
DEFAULT_TTL_SECONDS = 900


class MLBGameContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class MLBGameContextSnapshot:
    game_id: str
    retrieved_at: str
    source: str
    weather: dict[str, Any]
    umpire: dict[str, Any]
    lineups: tuple[dict[str, Any], ...]
    catchers: tuple[dict[str, Any], ...]


def _fetch_json(url: str, *, opener: Callable = urlopen) -> Mapping[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-MLB-context/1"})
    try:
        with opener(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBGameContextError(f"MLB_CONTEXT_FETCH_FAILED:{type(exc).__name__}:{exc}") from exc
    if not isinstance(payload, Mapping):
        raise MLBGameContextError("MLB_CONTEXT_RESPONSE_NOT_OBJECT")
    return payload


def _player_id(value: Any) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _weather(game_data: Mapping[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    raw = game_data.get("weather") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    wind = str(raw.get("wind") or "").strip()
    temp = raw.get("temp")
    condition = str(raw.get("condition") or "").strip() or None
    return {
        "source": SOURCE,
        "provider_tier": "PRIMARY_CONTEXT",
        "retrieved_at": retrieved_at.isoformat(),
        "ttl_seconds": 1800,
        "temperature_f": temp,
        "condition": condition,
        "wind_text": wind or None,
        "roof_state": str((game_data.get("venue") or {}).get("roofType") or "").strip() or None,
    }


def _umpire(live_data: Mapping[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    officials = ((live_data.get("boxscore") or {}).get("officials") or [])
    for row in officials:
        if not isinstance(row, Mapping):
            continue
        official_type = str(row.get("officialType") or "").lower()
        if "home plate" not in official_type:
            continue
        person = row.get("official") or {}
        return {
            "source": SOURCE,
            "provider_tier": "PRIMARY_CONTEXT",
            "retrieved_at": retrieved_at.isoformat(),
            "ttl_seconds": 3600,
            "home_plate_umpire_id": _player_id(person.get("id")),
            "home_plate_umpire_name": str(person.get("fullName") or "").strip() or None,
        }
    return {
        "source": SOURCE,
        "provider_tier": "PRIMARY_CONTEXT",
        "retrieved_at": retrieved_at.isoformat(),
        "ttl_seconds": 3600,
        "home_plate_umpire_id": None,
        "home_plate_umpire_name": None,
    }


def _team_context(team_box: Mapping[str, Any], *, side: str, team_id: Any, retrieved_at: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    batting_order = team_box.get("battingOrder") or []
    players = team_box.get("players") or {}
    order_lookup = {int(pid): idx + 1 for idx, pid in enumerate(batting_order) if _player_id(pid) is not None}
    lineups: list[dict[str, Any]] = []
    catchers: list[dict[str, Any]] = []
    if not isinstance(players, Mapping):
        return lineups, catchers
    for row in players.values():
        if not isinstance(row, Mapping):
            continue
        person = row.get("person") or {}
        pid = _player_id(person.get("id"))
        if pid is None:
            continue
        pos = row.get("position") or {}
        pos_abbr = str(pos.get("abbreviation") or "").upper().strip()
        order = order_lookup.get(pid)
        if order is not None:
            lineups.append({
                "source": SOURCE,
                "provider_tier": "PRIMARY_CONTEXT",
                "retrieved_at": retrieved_at.isoformat(),
                "ttl_seconds": DEFAULT_TTL_SECONDS,
                "team_id": str(team_id),
                "side": side,
                "player_id": str(pid),
                "player_name": str(person.get("fullName") or "").strip(),
                "batting_order": order,
                "starter_status": "CONFIRMED_STARTER",
                "position": pos_abbr or None,
            })
        if pos_abbr == "C" and order is not None:
            catchers.append({
                "source": SOURCE,
                "provider_tier": "PRIMARY_CONTEXT",
                "retrieved_at": retrieved_at.isoformat(),
                "ttl_seconds": DEFAULT_TTL_SECONDS,
                "team_id": str(team_id),
                "side": side,
                "catcher_id": str(pid),
                "catcher_name": str(person.get("fullName") or "").strip(),
                "batting_order": order,
            })
    lineups.sort(key=lambda x: x["batting_order"])
    return lineups, catchers


def parse_game_context(payload: Mapping[str, Any], *, game_pk: int, retrieved_at: datetime | None = None) -> MLBGameContextSnapshot:
    now = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    game_data = payload.get("gameData") or {}
    live_data = payload.get("liveData") or {}
    if not isinstance(game_data, Mapping) or not isinstance(live_data, Mapping):
        raise MLBGameContextError("MLB_CONTEXT_SHAPE_INVALID")
    teams = game_data.get("teams") or {}
    box_teams = ((live_data.get("boxscore") or {}).get("teams") or {})
    lineups: list[dict[str, Any]] = []
    catchers: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team = teams.get(side) or {}
        team_id = team.get("id")
        team_box = box_teams.get(side) or {}
        l, c = _team_context(team_box, side=side.upper(), team_id=team_id, retrieved_at=now)
        lineups.extend(l)
        catchers.extend(c)
    return MLBGameContextSnapshot(
        game_id=str(game_pk),
        retrieved_at=now.isoformat(),
        source=SOURCE,
        weather=_weather(game_data, now),
        umpire=_umpire(live_data, now),
        lineups=tuple(lineups),
        catchers=tuple(catchers),
    )


def fetch_game_context(game_pk: int, *, opener: Callable = urlopen, now: datetime | None = None) -> MLBGameContextSnapshot:
    if int(game_pk) <= 0:
        raise ValueError("game_pk must be positive")
    payload = _fetch_json(BASE.format(game_pk=int(game_pk)), opener=opener)
    return parse_game_context(payload, game_pk=int(game_pk), retrieved_at=now)
