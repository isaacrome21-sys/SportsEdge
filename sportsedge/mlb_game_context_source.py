"""MLB gameday context acquisition from StatsAPI live game feeds.

Weather, lineups, plate umpire and starting catcher are acquired separately and
carry source-specific verification metadata. Missing-but-not-yet-published fields
are represented explicitly; they are not confused with stale collector output.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
SOURCE = "MLB_STATSAPI_LIVE_FEED"

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
    source_states: dict[str, str]

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
    if not isinstance(raw, Mapping): raw = {}
    dt_obj = game_data.get("datetime") or {}
    first_pitch = dt_obj.get("dateTime") if isinstance(dt_obj, Mapping) else None
    venue = game_data.get("venue") or {}
    roof_state = str(venue.get("roofType") or "").strip() or None if isinstance(venue, Mapping) else None
    return {"source": SOURCE, "provider_tier": "PRIMARY_GAME_CONTEXT", "retrieved_at": retrieved_at.isoformat(), "forecast_retrieved_at": retrieved_at.isoformat(), "forecast_valid_at": first_pitch, "ttl_seconds": 3600, "temperature_f": raw.get("temp"), "condition": str(raw.get("condition") or "").strip() or None, "wind_text": str(raw.get("wind") or "").strip() or None, "roof_state": roof_state}

def _umpire(live_data: Mapping[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    officials = ((live_data.get("boxscore") or {}).get("officials") or [])
    for row in officials:
        if not isinstance(row, Mapping) or "home plate" not in str(row.get("officialType") or "").lower(): continue
        person = row.get("official") or {}
        return {"source": SOURCE, "provider_tier": "PRIMARY_GAME_CONTEXT", "retrieved_at": retrieved_at.isoformat(), "last_verified_at": retrieved_at.isoformat(), "ttl_seconds": 43200, "availability_state": "PRESENT", "home_plate_umpire_id": _player_id(person.get("id")), "home_plate_umpire_name": str(person.get("fullName") or "").strip() or None}
    return {"source": SOURCE, "provider_tier": "PRIMARY_GAME_CONTEXT", "retrieved_at": retrieved_at.isoformat(), "last_verified_at": retrieved_at.isoformat(), "ttl_seconds": 43200, "availability_state": "ABSENT_NOT_YET_POSTED", "home_plate_umpire_id": None, "home_plate_umpire_name": None}

def _team_context(team_box: Mapping[str, Any], *, side: str, team_id: Any, retrieved_at: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    batting_order = team_box.get("battingOrder") or []
    players = team_box.get("players") or {}
    order_lookup = {int(pid): idx + 1 for idx, pid in enumerate(batting_order) if _player_id(pid) is not None}
    lineups, catchers = [], []
    if not isinstance(players, Mapping): return lineups, catchers
    for row in players.values():
        if not isinstance(row, Mapping): continue
        person = row.get("person") or {}; pid = _player_id(person.get("id"))
        if pid is None: continue
        pos = row.get("position") or {}; pos_abbr = str(pos.get("abbreviation") or "").upper().strip(); order = order_lookup.get(pid)
        if order is not None:
            lineups.append({"source": SOURCE, "provider_tier": "PRIMARY_GAME_CONTEXT", "retrieved_at": retrieved_at.isoformat(), "last_verified_at": retrieved_at.isoformat(), "ttl_seconds": 1200, "team_id": str(team_id), "side": side, "player_id": str(pid), "player_name": str(person.get("fullName") or "").strip(), "batting_order": order, "starter_status": "CONFIRMED_STARTER", "position": pos_abbr or None})
        if pos_abbr == "C" and order is not None:
            catchers.append({"source": SOURCE, "provider_tier": "PRIMARY_GAME_CONTEXT", "retrieved_at": retrieved_at.isoformat(), "last_verified_at": retrieved_at.isoformat(), "ttl_seconds": 43200, "availability_state": "PRESENT", "team_id": str(team_id), "side": side, "catcher_id": str(pid), "catcher_name": str(person.get("fullName") or "").strip(), "batting_order": order})
    lineups.sort(key=lambda x: x["batting_order"])
    return lineups, catchers

def parse_game_context(payload: Mapping[str, Any], *, game_pk: int, retrieved_at: datetime | None = None) -> MLBGameContextSnapshot:
    now = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    game_data = payload.get("gameData") or {}; live_data = payload.get("liveData") or {}
    if not isinstance(game_data, Mapping) or not isinstance(live_data, Mapping): raise MLBGameContextError("MLB_CONTEXT_SHAPE_INVALID")
    teams = game_data.get("teams") or {}; box_teams = ((live_data.get("boxscore") or {}).get("teams") or {})
    lineups, catchers = [], []
    for side in ("away", "home"):
        team = teams.get(side) or {}; team_id = team.get("id"); team_box = box_teams.get(side) or {}
        l, c = _team_context(team_box, side=side.upper(), team_id=team_id, retrieved_at=now); lineups.extend(l); catchers.extend(c)
    weather = _weather(game_data, now); umpire = _umpire(live_data, now)
    source_states = {"weather_first_pitch_forecast": "PRESENT" if any(weather.get(k) is not None for k in ("temperature_f", "condition", "wind_text", "roof_state")) else "ABSENT", "confirmed_lineup": "PRESENT" if len(lineups) >= 18 else "ABSENT", "plate_umpire": "PRESENT" if umpire.get("home_plate_umpire_id") else "ABSENT", "starting_catcher": "PRESENT" if len(catchers) >= 2 else "ABSENT"}
    return MLBGameContextSnapshot(str(game_pk), now.isoformat(), SOURCE, weather, umpire, tuple(lineups), tuple(catchers), source_states)

def fetch_game_context(game_pk: int, *, opener: Callable = urlopen, now: datetime | None = None) -> MLBGameContextSnapshot:
    if int(game_pk) <= 0: raise ValueError("game_pk must be positive")
    return parse_game_context(_fetch_json(BASE.format(game_pk=int(game_pk)), opener=opener), game_pk=int(game_pk), retrieved_at=now)
