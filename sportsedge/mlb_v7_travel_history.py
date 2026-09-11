from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://statsapi.mlb.com"
_TIMECODE_RE = re.compile(r"^\d{8}_\d{6}$")


class MLBV7TravelHistoryError(RuntimeError):
    """Raised when historical MLB travel evidence is missing or unverifiable."""


@dataclass(frozen=True)
class HistoricalGameRow:
    game_id: int
    team_id: int
    opponent_team_id: int
    venue_id: int
    game_start_time: str
    status: str
    final_at: str
    final_at_semantics: str
    official_date: str
    game_type: str
    side: str
    final_timecode: str


@dataclass(frozen=True)
class VenueReferenceRow:
    venue_id: int
    latitude: float
    longitude: float
    timezone: str


def _get_json(url: str, opener: Callable = urlopen) -> Any:
    try:
        with opener(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBV7TravelHistoryError(f"MLB_STATSAPI_FETCH_FAILED:{url}:{type(exc).__name__}") from exc


def _iso_utc(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MLBV7TravelHistoryError(f"{field}_MISSING")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBV7TravelHistoryError(f"{field}_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBV7TravelHistoryError(f"{field}_NOT_TIMEZONE_AWARE")
    return dt.astimezone(timezone.utc).isoformat()


def timecode_to_utc_iso(timecode: str) -> str:
    if not isinstance(timecode, str) or not _TIMECODE_RE.fullmatch(timecode):
        raise MLBV7TravelHistoryError("TIMECODE_INVALID")
    try:
        dt = datetime.strptime(timecode, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise MLBV7TravelHistoryError("TIMECODE_INVALID") from exc
    return dt.isoformat()


def extract_timecodes(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        candidates = payload.get("timestamps")
    else:
        candidates = payload
    if not isinstance(candidates, list) or not candidates:
        raise MLBV7TravelHistoryError("FINAL_GAME_TIMESTAMPS_MISSING")
    out: list[str] = []
    for value in candidates:
        if not isinstance(value, str) or not _TIMECODE_RE.fullmatch(value):
            raise MLBV7TravelHistoryError("TIMECODE_INVALID")
        timecode_to_utc_iso(value)
        out.append(value)
    if len(out) != len(set(out)):
        raise MLBV7TravelHistoryError("TIMECODE_DUPLICATE")
    if out != sorted(out):
        raise MLBV7TravelHistoryError("TIMECODE_ORDER_INVALID")
    return out


def snapshot_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise MLBV7TravelHistoryError("FINAL_SNAPSHOT_INVALID")
    status = ((payload.get("gameData") or {}).get("status") or {}).get("abstractGameState")
    if not isinstance(status, str) or not status:
        raise MLBV7TravelHistoryError("FINAL_SNAPSHOT_STATUS_MISSING")
    return status


def schedule_games(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise MLBV7TravelHistoryError("SCHEDULE_PAYLOAD_INVALID")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for date_block in payload.get("dates") or []:
        if not isinstance(date_block, dict):
            raise MLBV7TravelHistoryError("SCHEDULE_DATE_BLOCK_INVALID")
        for game in date_block.get("games") or []:
            if not isinstance(game, dict):
                raise MLBV7TravelHistoryError("SCHEDULE_GAME_INVALID")
            teams = game.get("teams") or {}
            away = ((teams.get("away") or {}).get("team") or {})
            home = ((teams.get("home") or {}).get("team") or {})
            status_obj = game.get("status") or {}
            venue = game.get("venue") or {}
            try:
                game_id = int(game["gamePk"])
                away_id = int(away["id"])
                home_id = int(home["id"])
                venue_id = int(venue["id"])
            except Exception as exc:
                raise MLBV7TravelHistoryError("SCHEDULE_GAME_IDENTITY_INCOMPLETE") from exc
            if game_id in seen:
                raise MLBV7TravelHistoryError("SCHEDULE_GAME_DUPLICATE")
            seen.add(game_id)
            start = _iso_utc(game.get("gameDate"), "GAME_START_TIME")
            status = status_obj.get("abstractGameState")
            if not isinstance(status, str) or not status:
                raise MLBV7TravelHistoryError("SCHEDULE_STATUS_MISSING")
            official_date = game.get("officialDate") or date_block.get("date")
            if not isinstance(official_date, str) or not official_date:
                raise MLBV7TravelHistoryError("OFFICIAL_DATE_MISSING")
            game_type = game.get("gameType")
            if not isinstance(game_type, str) or not game_type:
                raise MLBV7TravelHistoryError("GAME_TYPE_MISSING")
            out.append({
                "game_id": game_id,
                "away_team_id": away_id,
                "home_team_id": home_id,
                "venue_id": venue_id,
                "game_start_time": start,
                "status": status,
                "official_date": official_date,
                "game_type": game_type,
            })
    out.sort(key=lambda row: (row["game_start_time"], row["game_id"]))
    return out


def normalize_final_game(game: dict[str, Any], timestamps_payload: Any, final_snapshot_payload: Any) -> list[HistoricalGameRow]:
    if game.get("status") != "Final":
        raise MLBV7TravelHistoryError("SCHEDULE_GAME_NOT_FINAL")
    timecodes = extract_timecodes(timestamps_payload)
    final_timecode = timecodes[-1]
    if snapshot_status(final_snapshot_payload) != "Final":
        raise MLBV7TravelHistoryError("LAST_TIMECODE_NOT_FINAL")
    final_at = timecode_to_utc_iso(final_timecode)
    start_at = _iso_utc(game.get("game_start_time"), "GAME_START_TIME")
    if datetime.fromisoformat(final_at) < datetime.fromisoformat(start_at):
        raise MLBV7TravelHistoryError("FINAL_AT_BEFORE_GAME_START")
    try:
        game_id = int(game["game_id"])
        away_id = int(game["away_team_id"])
        home_id = int(game["home_team_id"])
        venue_id = int(game["venue_id"])
    except Exception as exc:
        raise MLBV7TravelHistoryError("NORMALIZED_GAME_IDENTITY_INVALID") from exc
    if min(game_id, away_id, home_id, venue_id) <= 0:
        raise MLBV7TravelHistoryError("NORMALIZED_GAME_IDENTITY_INVALID")
    official_date = str(game.get("official_date") or "")
    game_type = str(game.get("game_type") or "")
    if not official_date or not game_type:
        raise MLBV7TravelHistoryError("NORMALIZED_GAME_METADATA_INCOMPLETE")
    semantics = "LAST_HISTORICAL_TIMECODE_CONFIRMED_FINAL_UPPER_BOUND"
    common = {
        "game_id": game_id,
        "venue_id": venue_id,
        "game_start_time": start_at,
        "status": "Final",
        "final_at": final_at,
        "final_at_semantics": semantics,
        "official_date": official_date,
        "game_type": game_type,
        "final_timecode": final_timecode,
    }
    return [
        HistoricalGameRow(team_id=away_id, opponent_team_id=home_id, side="away", **common),
        HistoricalGameRow(team_id=home_id, opponent_team_id=away_id, side="home", **common),
    ]


def parse_venue_reference(payload: Any, expected_venue_id: int) -> VenueReferenceRow:
    if not isinstance(payload, dict):
        raise MLBV7TravelHistoryError("VENUE_PAYLOAD_INVALID")
    venues = payload.get("venues")
    if not isinstance(venues, list) or len(venues) != 1 or not isinstance(venues[0], dict):
        raise MLBV7TravelHistoryError("VENUE_RESPONSE_NOT_SINGLETON")
    venue = venues[0]
    try:
        venue_id = int(venue["id"])
    except Exception as exc:
        raise MLBV7TravelHistoryError("VENUE_ID_MISSING") from exc
    if venue_id != int(expected_venue_id):
        raise MLBV7TravelHistoryError("VENUE_ID_MISMATCH")
    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    lat = coordinates.get("latitude", location.get("latitude"))
    lon = coordinates.get("longitude", location.get("longitude"))
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as exc:
        raise MLBV7TravelHistoryError("VENUE_COORDINATES_MISSING") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise MLBV7TravelHistoryError("VENUE_COORDINATES_INVALID")
    tz = venue.get("timeZone") or {}
    tz_id = tz.get("id") if isinstance(tz, dict) else None
    if not isinstance(tz_id, str) or not tz_id or "/" not in tz_id:
        raise MLBV7TravelHistoryError("VENUE_TIMEZONE_MISSING")
    return VenueReferenceRow(venue_id=venue_id, latitude=latitude, longitude=longitude, timezone=tz_id)


def schedule_url(start_date: str, end_date: str) -> str:
    query = urlencode({"sportId": 1, "startDate": start_date, "endDate": end_date, "hydrate": "team,venue"})
    return f"{BASE}/api/v1/schedule?{query}"


def timestamps_url(game_id: int) -> str:
    return f"{BASE}/api/v1.1/game/{int(game_id)}/feed/live/timestamps"


def historical_snapshot_url(game_id: int, timecode: str) -> str:
    query = urlencode({"timecode": timecode, "fields": "gameData,status,abstractGameState,detailedState,metaData,timeStamp"})
    return f"{BASE}/api/v1.1/game/{int(game_id)}/feed/live?{query}"


def venue_url(venue_id: int) -> str:
    query = urlencode({"hydrate": "location,timezone"})
    return f"{BASE}/api/v1/venues/{int(venue_id)}?{query}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> str:
    data = _canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256_bytes(data)


def write_jsonl(path: Path, rows: Iterable[Any]) -> str:
    material = []
    for row in rows:
        material.append(asdict(row) if hasattr(row, "__dataclass_fields__") else row)
    lines = b"".join(_canonical_json_bytes(row) for row in material)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lines)
    return _sha256_bytes(lines)


def build_source_manifest(*, source_class: str, coverage_start: str, coverage_end: str, fields: list[str], semantics: dict[str, Any], evidence_files: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "source_class": source_class,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "fields": list(fields),
        "semantics": dict(semantics),
        "evidence_files": list(evidence_files),
    }


def probe_one_final_game(date_iso: str, opener: Callable = urlopen) -> dict[str, Any]:
    report: dict[str, Any] = {
        "contract": "SPORTSEDGE_MLB_V7_TRAVEL_HISTORY_SOURCE_PROBE_V1",
        "date": date_iso,
        "promotion_authority": False,
        "attestation_written": False,
        "candidate_training_allowed": False,
        "blockers": ["FULL_2023_2025_COVERAGE_NOT_COLLECTED", "DECISION_TIME_BINDING_NOT_ATTESTED"],
    }
    try:
        games = schedule_games(_get_json(schedule_url(date_iso, date_iso), opener))
        finals = [game for game in games if game["status"] == "Final"]
        if not finals:
            raise MLBV7TravelHistoryError("NO_FINAL_GAME_ON_PROBE_DATE")
        game = finals[0]
        timecodes_payload = _get_json(timestamps_url(game["game_id"]), opener)
        timecodes = extract_timecodes(timecodes_payload)
        last_timecode = timecodes[-1]
        final_snapshot = _get_json(historical_snapshot_url(game["game_id"], last_timecode), opener)
        rows = normalize_final_game(game, timecodes_payload, final_snapshot)
        venue = parse_venue_reference(_get_json(venue_url(game["venue_id"]), opener), game["venue_id"])
        report.update({
            "state": "PASS_SOURCE_PROBE",
            "game_id": game["game_id"],
            "team_row_count": len(rows),
            "timecode_count": len(timecodes),
            "first_timecode": timecodes[0],
            "last_timecode": last_timecode,
            "final_at": rows[0].final_at,
            "final_at_semantics": rows[0].final_at_semantics,
            "historical_snapshot_status": snapshot_status(final_snapshot),
            "venue": asdict(venue),
        })
    except MLBV7TravelHistoryError as exc:
        report.update({"state": "BLOCKED_SOURCE_PROBE", "reason": str(exc)})
    return report
