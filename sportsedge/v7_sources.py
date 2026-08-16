from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .runtime import parse_timestamp

MLB_STATSAPI = "https://statsapi.mlb.com/api/v1"
SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
NWS_API = "https://api.weather.gov"
V7_SOURCE_SCHEMA_VERSION = "mlb_v7_sources_v1"


class V7SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceSnapshot:
    provider: str
    source_url: str
    retrieved_at: str
    parser_version: str
    payload_sha256: str
    payload: Any


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise V7SourceError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise V7SourceError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _read_response(response: Any) -> bytes:
    data = response.read()
    if not isinstance(data, (bytes, bytearray)):
        raise V7SourceError("HTTP response must yield bytes")
    return bytes(data)


def _open_bytes(url: str, *, opener: Callable = urlopen, timeout: int = 20, headers: Mapping[str, str] | None = None) -> bytes:
    request = Request(url, headers=dict(headers or {}))
    try:
        response = opener(request, timeout=timeout)
        if hasattr(response, "__enter__"):
            with response as r:
                return _read_response(r)
        return _read_response(response)
    except Exception as exc:
        raise V7SourceError(f"source fetch failed: {url}") from exc


def snapshot_json(*, provider: str, url: str, opener: Callable = urlopen, retrieved_at: Any | None = None, parser_version: str = "json_v1", headers: Mapping[str, str] | None = None) -> SourceSnapshot:
    raw = _open_bytes(url, opener=opener, headers=headers)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise V7SourceError("invalid JSON payload") from exc
    now = _utc(retrieved_at or datetime.now(timezone.utc), "retrieved_at")
    return SourceSnapshot(provider=provider, source_url=url, retrieved_at=now.isoformat(), parser_version=parser_version, payload_sha256=hashlib.sha256(raw).hexdigest(), payload=payload)


def snapshot_csv(*, provider: str, url: str, opener: Callable = urlopen, retrieved_at: Any | None = None, parser_version: str = "csv_dict_v1", headers: Mapping[str, str] | None = None) -> SourceSnapshot:
    raw = _open_bytes(url, opener=opener, headers=headers)
    try:
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:
        raise V7SourceError("invalid CSV payload") from exc
    now = _utc(retrieved_at or datetime.now(timezone.utc), "retrieved_at")
    return SourceSnapshot(provider=provider, source_url=url, retrieved_at=now.isoformat(), parser_version=parser_version, payload_sha256=hashlib.sha256(raw).hexdigest(), payload=rows)


def mlb_schedule_url(date_iso: str) -> str:
    return f"{MLB_STATSAPI}/schedule?" + urlencode({"sportId": 1, "date": date_iso, "hydrate": "probablePitcher,venue"})


def mlb_live_feed_url(game_pk: int) -> str:
    if int(game_pk) <= 0:
        raise V7SourceError("invalid game_pk")
    return f"{MLB_STATSAPI}.1/game/{int(game_pk)}/feed/live"


def fetch_mlb_schedule(date_iso: str, *, opener: Callable = urlopen, retrieved_at: Any | None = None) -> SourceSnapshot:
    return snapshot_json(provider="MLB_STATSAPI_SCHEDULE", url=mlb_schedule_url(date_iso), opener=opener, retrieved_at=retrieved_at, parser_version="mlb_schedule_v1")


def fetch_mlb_live_feed(game_pk: int, *, opener: Callable = urlopen, retrieved_at: Any | None = None) -> SourceSnapshot:
    # v1.1 live feed is the stable public StatsAPI path used elsewhere in SportsEdge.
    url = f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live"
    return snapshot_json(provider="MLB_STATSAPI_LIVE_FEED", url=url, opener=opener, retrieved_at=retrieved_at, parser_version="mlb_live_feed_v1")


def savant_statcast_url(start_date: str, end_date: str, *, player_type: str = "batter") -> str:
    ptype = str(player_type).strip().lower()
    if ptype not in {"batter", "pitcher"}:
        raise V7SourceError("player_type must be batter or pitcher")
    params = {
        "type": "details",
        "player_type": ptype,
        "game_date_gt": start_date,
        "game_date_lt": end_date,
    }
    return SAVANT_CSV + "?" + urlencode(params)


def fetch_savant_statcast(start_date: str, end_date: str, *, player_type: str = "batter", opener: Callable = urlopen, retrieved_at: Any | None = None) -> SourceSnapshot:
    return snapshot_csv(provider="BASEBALL_SAVANT_STATCAST", url=savant_statcast_url(start_date, end_date, player_type=player_type), opener=opener, retrieved_at=retrieved_at, parser_version="savant_statcast_csv_v1")


def fetch_nws_hourly(lat: float, lon: float, *, opener: Callable = urlopen, retrieved_at: Any | None = None, user_agent: str = "SportsEdge/1.0") -> tuple[SourceSnapshot, SourceSnapshot]:
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    point_url = f"{NWS_API}/points/{float(lat):.4f},{float(lon):.4f}"
    point = snapshot_json(provider="NWS_POINTS", url=point_url, opener=opener, retrieved_at=retrieved_at, parser_version="nws_points_v1", headers=headers)
    try:
        forecast_url = str(point.payload["properties"]["forecastHourly"])
    except Exception as exc:
        raise V7SourceError("NWS points payload missing forecastHourly") from exc
    forecast = snapshot_json(provider="NWS_HOURLY_FORECAST", url=forecast_url, opener=opener, retrieved_at=retrieved_at, parser_version="nws_hourly_v1", headers=headers)
    return point, forecast


def extract_home_plate_umpire(live_feed: Mapping[str, Any]) -> dict[str, Any] | None:
    officials = (((live_feed.get("liveData") or {}).get("boxscore") or {}).get("officials") or [])
    for row in officials:
        if str((row or {}).get("officialType") or "").strip().lower() == "home plate":
            official = (row or {}).get("official") or {}
            if official.get("id"):
                return {"umpire_id": int(official["id"]), "umpire_name": str(official.get("fullName") or "")}
    return None


def extract_starting_catcher_ids(live_feed: Mapping[str, Any]) -> dict[str, int | None]:
    teams = (((live_feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {})
    out: dict[str, int | None] = {"away": None, "home": None}
    for side in ("away", "home"):
        team = teams.get(side) or {}
        players = team.get("players") or {}
        batting_order = {int(x) for x in (team.get("battingOrder") or [])}
        for player in players.values():
            person = (player or {}).get("person") or {}
            position = (player or {}).get("position") or {}
            pid = person.get("id")
            if pid and int(pid) in batting_order and str(position.get("abbreviation") or "").upper() == "C":
                out[side] = int(pid)
                break
    return out


def source_manifest(snapshot: SourceSnapshot) -> dict[str, Any]:
    value = asdict(snapshot)
    value.pop("payload", None)
    value["schema_version"] = V7_SOURCE_SCHEMA_VERSION
    return value
