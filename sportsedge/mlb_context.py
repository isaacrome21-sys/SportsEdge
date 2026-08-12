"""MLB-native bettor context that is informative but never model-driving."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .mlb_source import GameSnapshot

BASE = "https://statsapi.mlb.com"


class MLBContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class GameContext:
    game_id: str
    away_team: str
    home_team: str
    away_probable_pitcher: str | None
    home_probable_pitcher: str | None
    venue_name: str | None
    roof_type: str | None
    weather_status: str
    weather: dict[str, Any] | None
    plate_umpire_status: str
    plate_umpire: dict[str, Any] | None
    source: str = "MLB_STATSAPI_LIVE_FEED"
    error: str | None = None


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "SportsEdge/1.0", "Accept": "application/json"})
    try:
        with opener(req, timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBContextError(f"MLB_CONTEXT_FETCH_FAILED: {type(exc).__name__}: {exc}") from exc
    if not isinstance(value, dict):
        raise MLBContextError("MLB_CONTEXT_PAYLOAD_NOT_OBJECT")
    return value


def _plate_umpire(officials: Any) -> dict[str, Any] | None:
    if not isinstance(officials, list):
        return None
    for row in officials:
        if not isinstance(row, Mapping):
            continue
        role = str(row.get("officialType") or "").strip().lower()
        if role not in {"home plate", "homeplate", "plate"}:
            continue
        official = row.get("official") or {}
        if not isinstance(official, Mapping):
            return None
        name = str(official.get("fullName") or "").strip()
        if not name:
            return None
        out: dict[str, Any] = {"name": name}
        if official.get("id") is not None:
            try:
                out["id"] = int(official["id"])
            except (TypeError, ValueError):
                pass
        return out
    return None


def parse_context(snapshot: GameSnapshot, payload: Mapping[str, Any]) -> GameContext:
    game_data = payload.get("gameData") or {}
    live_data = payload.get("liveData") or {}
    if not isinstance(game_data, Mapping) or not isinstance(live_data, Mapping):
        raise MLBContextError("MLB_CONTEXT_SHAPE_INVALID")

    venue = game_data.get("venue") or {}
    if not isinstance(venue, Mapping):
        venue = {}
    field_info = venue.get("fieldInfo") or {}
    if not isinstance(field_info, Mapping):
        field_info = {}
    venue_name = str(venue.get("name") or "").strip() or None
    roof_type = str(field_info.get("roofType") or "").strip() or None

    raw_weather = game_data.get("weather")
    if isinstance(raw_weather, Mapping) and raw_weather:
        weather_status = "POSTED"
        weather = dict(raw_weather)
    else:
        weather_status = "NOT_POSTED"
        weather = None

    boxscore = live_data.get("boxscore") or {}
    if not isinstance(boxscore, Mapping):
        boxscore = {}
    plate = _plate_umpire(boxscore.get("officials"))
    plate_status = "POSTED" if plate is not None else "NOT_POSTED"

    probables = game_data.get("probablePitchers") or {}
    if not isinstance(probables, Mapping):
        probables = {}
    away_p = probables.get("away") or {}
    home_p = probables.get("home") or {}
    away_name = str(away_p.get("fullName") or "").strip() if isinstance(away_p, Mapping) else ""
    home_name = str(home_p.get("fullName") or "").strip() if isinstance(home_p, Mapping) else ""

    return GameContext(
        game_id=str(snapshot.game_pk),
        away_team=snapshot.away_name,
        home_team=snapshot.home_name,
        away_probable_pitcher=away_name or snapshot.away_probable_pitcher_name,
        home_probable_pitcher=home_name or snapshot.home_probable_pitcher_name,
        venue_name=venue_name,
        roof_type=roof_type,
        weather_status=weather_status,
        weather=weather,
        plate_umpire_status=plate_status,
        plate_umpire=plate,
    )


def fetch_slate_context(schedule: list[GameSnapshot], *, opener: Callable = urlopen) -> list[GameContext]:
    """Return one context row per scheduled game; failures are explicit, never dropped."""
    rows: list[GameContext] = []
    seen: set[int] = set()
    for snapshot in schedule:
        if snapshot.game_pk in seen:
            rows.append(GameContext(
                str(snapshot.game_pk), snapshot.away_name, snapshot.home_name,
                snapshot.away_probable_pitcher_name, snapshot.home_probable_pitcher_name,
                None, None, "FETCH_FAILED", None, "FETCH_FAILED", None,
                error="DUPLICATE_GAME_PK",
            ))
            continue
        seen.add(snapshot.game_pk)
        try:
            payload = _get_json(f"{BASE}/api/v1.1/game/{int(snapshot.game_pk)}/feed/live", opener)
            rows.append(parse_context(snapshot, payload))
        except Exception as exc:
            rows.append(GameContext(
                str(snapshot.game_pk), snapshot.away_name, snapshot.home_name,
                snapshot.away_probable_pitcher_name, snapshot.home_probable_pitcher_name,
                None, None, "FETCH_FAILED", None, "FETCH_FAILED", None,
                error=f"{type(exc).__name__}: {exc}",
            ))
    return rows


def context_to_dict(value: GameContext) -> dict[str, Any]:
    return asdict(value)
