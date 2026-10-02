"""Frozen historical weather transport for the CFB SportsDataverse lane.

The transport is season-scoped and game-id keyed. It normalizes CFBD's published
`/games/weather` rows into the exact three contextual fields consumed by the
SportsDataverse candidate model. Missing evaluated games fail closed; no market
data, interpolation, or weather imputation is permitted.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

class SDVWeatherTransportError(ValueError):
    pass

SOURCE_ID = "CFBD_GAMES_WEATHER_V1"
BASE_URL = "https://api.collegefootballdata.com/games/weather"


def request_params(*, season: int) -> dict[str, Any]:
    year = int(season)
    if not 2015 <= year <= 2025:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_SEASON_OUTSIDE_FROZEN_WINDOW")
    return {
        "year": year,
        "seasonType": "regular",
        "classification": "fbs",
    }


def _number(value: Any, field: str, game_id: int) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SDVWeatherTransportError(
            f"CFB_SDV_WEATHER_FIELD_INVALID:{game_id}:{field}"
        ) from exc
    if not isfinite(out):
        raise SDVWeatherTransportError(
            f"CFB_SDV_WEATHER_FIELD_INVALID:{game_id}:{field}"
        )
    return out


def normalize_season_weather(
    payload: Sequence[Mapping[str, Any]],
    *,
    season: int,
    evaluated_game_ids: Sequence[int],
) -> list[dict[str, Any]]:
    """Normalize one season and require complete coverage for evaluated games."""
    request_params(season=season)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_PAYLOAD_LIST_REQUIRED")
    required = {int(x) for x in evaluated_game_ids}
    if not required:
        return []

    rows: dict[int, dict[str, Any]] = {}
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise SDVWeatherTransportError("CFB_SDV_WEATHER_ROW_MAPPING_REQUIRED")
        try:
            game_id = int(raw.get("id"))
        except (TypeError, ValueError) as exc:
            raise SDVWeatherTransportError("CFB_SDV_WEATHER_GAME_ID_INVALID") from exc
        if game_id not in required:
            continue
        if game_id in rows:
            raise SDVWeatherTransportError(f"CFB_SDV_WEATHER_DUPLICATE_GAME:{game_id}")
        indoor = raw.get("gameIndoors")
        if type(indoor) is not bool:
            raise SDVWeatherTransportError(
                f"CFB_SDV_WEATHER_INDOOR_FLAG_REQUIRED:{game_id}"
            )
        if indoor:
            wind = None
            temperature = None
        else:
            wind = _number(raw.get("windSpeed"), "windSpeed", game_id)
            temperature = _number(raw.get("temperature"), "temperature", game_id)
        rows[game_id] = {
            "game_id": game_id,
            "game_indoor": indoor,
            "wind_speed": wind,
            "temperature": temperature,
        }

    missing = sorted(required - set(rows))
    if missing:
        raise SDVWeatherTransportError(
            "CFB_SDV_HISTORICAL_WEATHER_INCOMPLETE:" + ",".join(map(str, missing[:20]))
        )
    return [rows[gid] for gid in sorted(rows)]


__all__ = [
    "BASE_URL",
    "SOURCE_ID",
    "SDVWeatherTransportError",
    "normalize_season_weather",
    "request_params",
]
