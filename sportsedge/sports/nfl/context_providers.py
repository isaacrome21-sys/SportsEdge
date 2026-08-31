from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import atan2, cos, radians, sin, sqrt
from statistics import median
from typing import Any, Mapping, Sequence
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError, make_observation

AUTO = "AUTO"
ROOF_TYPES = frozenset({"FIXED", "RETRACTABLE", "OPEN_AIR"})
ROOF_DECISIONS = frozenset({"OPEN", "CLOSED", "UNKNOWN", "MISSING_ROOF_DECISION"})
INJURY_STATUSES = frozenset({"OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE", "INACTIVE", "MISSING"})
PRACTICE_STATUSES = frozenset({"DNP", "LP", "FP", "MISSING"})


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def _https(uri: str, field: str) -> str:
    value = str(uri or "").strip()
    if not value.startswith("https://"):
        raise NFLContextError(f"{field} must be https")
    return value


@dataclass(frozen=True)
class StadiumRecord:
    stadium_id: str
    name: str
    team_ids: tuple[str, ...]
    lat: float
    lon: float
    field_bearing_deg: float
    roof_type: str
    timezone_name: str
    typical_home_kickoff_hour_local: float
    version: str

    def validate(self) -> "StadiumRecord":
        if not self.stadium_id.strip() or not self.name.strip():
            raise NFLContextError("stadium identity required")
        if not self.team_ids:
            raise NFLContextError("stadium team_ids required")
        if not (-90 <= float(self.lat) <= 90 and -180 <= float(self.lon) <= 180):
            raise NFLContextError("stadium coordinates invalid")
        if not (0 <= float(self.field_bearing_deg) < 360):
            raise NFLContextError("field bearing invalid")
        if self.roof_type not in ROOF_TYPES:
            raise NFLContextError("roof type invalid")
        if not self.timezone_name.strip() or not self.version.strip():
            raise NFLContextError("stadium timezone/version required")
        if not (0 <= float(self.typical_home_kickoff_hour_local) < 24):
            raise NFLContextError("typical kickoff hour invalid")
        return self


def stadium_registry_hash(rows: Mapping[str, StadiumRecord]) -> str:
    payload = {key: asdict(value.validate()) for key, value in sorted(rows.items())}
    return canonical_sha256(payload)


def rotate_wind_to_field(*, wind_speed_mph: float, wind_dir_deg: float, field_bearing_deg: float) -> dict[str, float]:
    speed = float(wind_speed_mph)
    if speed < 0:
        raise NFLContextError("wind speed invalid")
    movement_to = (float(wind_dir_deg) + 180.0) % 360.0
    bearing = float(field_bearing_deg) % 360.0
    relative = ((movement_to - bearing + 540.0) % 360.0) - 180.0
    return {
        "speed_mph": speed,
        "dir_to_field_deg": relative,
        "along_field_mph": speed * cos(radians(relative)),
        "cross_field_mph": speed * sin(radians(relative)),
    }


def resolve_roof_decision(stadium: StadiumRecord, authoritative_roof: str | None) -> str:
    stadium.validate()
    if stadium.roof_type == "FIXED":
        return "CLOSED"
    if authoritative_roof not in (None, ""):
        value = str(authoritative_roof).upper().strip()
        if value not in {"OPEN", "CLOSED"}:
            raise NFLContextError("authoritative roof decision invalid")
        return value
    if stadium.roof_type == "RETRACTABLE":
        return "MISSING_ROOF_DECISION"
    return "UNKNOWN"


def select_hourly_period(periods: Sequence[Mapping[str, Any]], kickoff: Any) -> Mapping[str, Any] | None:
    target = _utc(kickoff, "kickoff")
    eligible: list[tuple[float, Mapping[str, Any]]] = []
    for raw in periods:
        start_raw = raw.get("startTime") or raw.get("start_time")
        if not start_raw:
            continue
        start = _utc(start_raw, "forecast start")
        eligible.append((abs((start - target).total_seconds()), raw))
    return min(eligible, key=lambda x: x[0])[1] if eligible else None


def fetch_nws_hourly_raw(*, lat: float, lon: float, opener=urlopen, user_agent: str = "SportsEdge/1.0") -> tuple[Mapping[str, Any], str, str]:
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    points_uri = f"https://api.weather.gov/points/{float(lat):.4f},{float(lon):.4f}"
    try:
        with opener(Request(points_uri, headers=headers), timeout=20) as response:
            points_bytes = response.read()
        points = json.loads(points_bytes.decode("utf-8"))
        hourly_uri = str(points["properties"]["forecastHourly"])
        with opener(Request(hourly_uri, headers=headers), timeout=20) as response:
            hourly_bytes = response.read()
        hourly = json.loads(hourly_bytes.decode("utf-8"))
    except Exception as exc:
        raise NFLContextError("NWS hourly fetch failed") from exc
    return hourly, hourly_uri, sha256(hourly_bytes).hexdigest()


def build_weather_roof_provider(*, game_id: str, stadium: StadiumRecord, kickoff: Any, as_of: Any, nws_payload: Mapping[str, Any], source_uri: str, source_sha256: str, authoritative_roof: str | None = None) -> Mapping[str, Any]:
    stadium.validate()
    _https(source_uri, "weather source_uri")
    pit = _utc(as_of, "as_of")
    period = select_hourly_period(((nws_payload.get("properties") or {}).get("periods") or []), kickoff)
    payload: dict[str, Any] = {
        "stadium_id": stadium.stadium_id,
        "game_id": str(game_id),
        "coords": {"lat": stadium.lat, "lon": stadium.lon},
        "roof_type": stadium.roof_type,
        "roof_decision": resolve_roof_decision(stadium, authoritative_roof),
        "temp_f": None,
        "wind_speed_mph": None,
        "wind_dir_deg": None,
        "wind_relative": None,
        "precip_prob": None,
        "precip_type": None,
        "humidity": None,
        "forecast_hour": None,
    }
    if period is not None:
        payload["forecast_hour"] = period.get("startTime") or period.get("start_time")
        if period.get("temperature") is not None:
            payload["temp_f"] = float(period["temperature"])
        precip = period.get("probabilityOfPrecipitation") or {}
        if isinstance(precip, Mapping) and precip.get("value") is not None:
            payload["precip_prob"] = float(precip["value"]) / 100.0
        humidity = period.get("relativeHumidity") or {}
        if isinstance(humidity, Mapping) and humidity.get("value") is not None:
            payload["humidity"] = float(humidity["value"])
        payload["precip_type"] = None if period.get("shortForecast") in (None, "") else str(period.get("shortForecast"))
        # NWS hourly does not reliably expose numeric direction degrees. Keep it missing unless a PIT-safe parser supplies it.
        if period.get("windSpeedMph") is not None:
            payload["wind_speed_mph"] = float(period["windSpeedMph"])
        if period.get("windDirDeg") is not None:
            payload["wind_dir_deg"] = float(period["windDirDeg"])
        if payload["wind_speed_mph"] is not None and payload["wind_dir_deg"] is not None:
            payload["wind_relative"] = rotate_wind_to_field(
                wind_speed_mph=payload["wind_speed_mph"],
                wind_dir_deg=payload["wind_dir_deg"],
                field_bearing_deg=stadium.field_bearing_deg,
            )
    status = "AVAILABLE" if period is not None else "MISSING_FORECAST_HOUR"
    return {
        "status": status,
        "payload": payload,
        "source_name": "NWS_HOURLY+STADIUM_REGISTRY",
        "source_uri": source_uri,
        "source_sha256": source_sha256,
        "observed_at": pit,
    }


def build_official_injury_provider(*, game_id: str, team_id: str, player_id: str, as_of: Any, source_uri: str, source_payload: Mapping[str, Any], official_source: bool) -> Mapping[str, Any]:
    if not official_source:
        raise NFLContextError("injury source must be official")
    _https(source_uri, "injury source_uri")
    status = str(source_payload.get("status") or "MISSING").upper().strip()
    if status not in INJURY_STATUSES:
        raise NFLContextError("injury status invalid")
    practice_history = {str(k): str(v).upper().strip() for k, v in dict(source_payload.get("practice_history") or {}).items()}
    if any(value not in PRACTICE_STATUSES for value in practice_history.values()):
        raise NFLContextError("practice status invalid")
    report_ts = source_payload.get("report_ts")
    if report_ts not in (None, "") and _utc(report_ts, "report_ts") > _utc(as_of, "as_of"):
        raise NFLContextError("injury report occurs after PIT as-of")
    payload = {
        "player_id": str(player_id),
        "team_id": str(team_id),
        "game_id": str(game_id),
        "status": status,
        "practice_history": practice_history,
        "report_ts": report_ts,
        "game_status": source_payload.get("game_status"),
        "return_from_ir_pup": source_payload.get("return_from_ir_pup"),
        "ramp_flag": source_payload.get("ramp_flag"),
    }
    return {
        "status": "AVAILABLE" if status != "MISSING" else "MISSING",
        "payload": payload,
        "source_name": "OFFICIAL_NFL_TEAM_INJURY_REPORT",
        "source_uri": source_uri,
        "source_sha256": canonical_sha256(source_payload),
        "observed_at": _utc(as_of, "as_of"),
    }


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6371.0088
    lat1, lon1, lat2, lon2 = map(radians, (float(a_lat), float(a_lon), float(b_lat), float(b_lon)))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return radius * 2 * atan2(sqrt(h), sqrt(max(0.0, 1 - h)))


def build_rest_travel_provider(*, game_id: str, team_id: str, as_of: Any, source_uri: str, source_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _https(source_uri, "schedule source_uri")
    kickoff = _utc(source_payload.get("kickoff_ts"), "kickoff_ts")
    previous = source_payload.get("previous_kickoff_ts")
    days_rest = None if previous in (None, "") else int((kickoff - _utc(previous, "previous_kickoff_ts")).total_seconds() // 86400)
    travel_distance = None
    coords = ("previous_lat", "previous_lon", "current_lat", "current_lon")
    if all(source_payload.get(key) is not None for key in coords):
        travel_distance = haversine_km(*(float(source_payload[key]) for key in coords))
    payload = {
        "team_id": str(team_id),
        "game_id": str(game_id),
        "days_rest": days_rest,
        "short_week": None if days_rest is None else days_rest < 7,
        "post_bye": None if days_rest is None else days_rest >= 12,
        "consec_road": None if source_payload.get("consec_road") is None else int(source_payload["consec_road"]),
        "travel_distance_km": travel_distance,
        "tz_shift_hours": None if source_payload.get("tz_shift_hours") is None else int(source_payload["tz_shift_hours"]),
        "neutral_or_intl": None if source_payload.get("neutral_or_intl") is None else bool(source_payload["neutral_or_intl"]),
        "body_clock_offset": None if source_payload.get("body_clock_offset") is None else float(source_payload["body_clock_offset"]),
    }
    return {
        "status": "AVAILABLE",
        "payload": payload,
        "source_name": "NFL_SCHEDULE+STADIUM_REGISTRY",
        "source_uri": source_uri,
        "source_sha256": canonical_sha256(source_payload),
        "observed_at": _utc(as_of, "as_of"),
    }


def _window(values: Sequence[Any], n: int) -> list[float]:
    return [float(v) for v in list(values)[-n:] if v is not None]


def _median(values: Sequence[Any], n: int) -> float | None:
    row = _window(values, n)
    return None if not row else float(median(row))


def _max(values: Sequence[Any], n: int) -> float | None:
    row = _window(values, n)
    return None if not row else max(row)


def build_workload_leash_provider(*, game_id: str, player_id: str, team_id: str, as_of: Any, source_uri: str, source_payload: Mapping[str, Any], injury_ramp_state: bool | None, short_week: bool | None) -> Mapping[str, Any]:
    _https(source_uri, "workload source_uri")
    snaps = list(source_payload.get("snaps") or [])
    shares = [float(v) for v in list(source_payload.get("snap_share") or []) if v is not None]
    med5, max5 = _median(snaps, 5), _max(snaps, 5)
    band = None
    if med5 is not None and max5 is not None:
        low, mid, high = med5 * 0.90, med5, max5 * 1.05
        if injury_ramp_state:
            low *= 0.80
            high *= 0.90
        if short_week:
            high *= 0.97
        band = {"low": round(low, 2), "mid": round(mid, 2), "high": round(high, 2)}
    payload = {
        "player_id": str(player_id), "team_id": str(team_id), "game_id": str(game_id),
        "snaps_median_3": _median(snaps, 3), "snaps_max_3": _max(snaps, 3),
        "snaps_median_5": med5, "snaps_max_5": max5,
        "routes_median_3": _median(list(source_payload.get("routes") or []), 3),
        "targets_median_3": _median(list(source_payload.get("targets") or []), 3),
        "carries_median_3": _median(list(source_payload.get("carries") or []), 3),
        "pass_attempts_median_3": _median(list(source_payload.get("pass_attempts") or []), 3),
        "pass_rush_snaps_median_3": _median(list(source_payload.get("pass_rush_snaps") or []), 3),
        "snap_share_trend": None if len(shares) < 2 else shares[-1] - shares[0],
        "injury_ramp_state": injury_ramp_state,
        "short_week": short_week,
        "projected_snap_band": band,
    }
    return {
        "status": "AVAILABLE" if snaps else "MISSING_WORKLOAD_HISTORY",
        "payload": payload,
        "source_name": "PIT_SNAP_USAGE_HISTORY",
        "source_uri": source_uri,
        "source_sha256": canonical_sha256(source_payload),
        "observed_at": _utc(as_of, "as_of"),
    }


def provider_to_observation(*, context_class: str, provider_row: Mapping[str, Any], pit_as_of: Any):
    return make_observation(
        context_class=context_class,
        status=str(provider_row.get("status") or "MISSING"),
        payload=provider_row.get("payload"),
        source_name=str(provider_row.get("source_name") or "OBJECTIVE_PROVIDER"),
        source_uri=str(provider_row.get("source_uri") or ""),
        source_sha256=str(provider_row.get("source_sha256") or ""),
        source_type="AUTO",
        collection_mode="AUTO",
        observed_at=provider_row.get("observed_at") or pit_as_of,
        pit_as_of=pit_as_of,
    )
