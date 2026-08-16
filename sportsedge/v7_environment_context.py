from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import atan2, cos, isfinite, radians, sin, sqrt
from typing import Any, Mapping

from .runtime import parse_timestamp
from .source_lineage import canonical_json_sha256
from .v7_baseball_features import assert_no_market_contamination

V7_CONTEXT_CONTRACT_VERSION = "mlb_v7_environment_context_v1"
EARTH_RADIUS_KM = 6371.0088


class V7ContextError(ValueError):
    pass


@dataclass(frozen=True)
class ParkContext:
    venue_id: int
    run_factor: float
    hr_factor_lhb: float
    hr_factor_rhb: float


@dataclass(frozen=True)
class WeatherContext:
    temperature_f: float
    humidity_pct: float
    pressure_hpa: float
    wind_mph: float
    wind_out_to_center_mph: float
    precip_probability: float
    roof_closed: float


@dataclass(frozen=True)
class TravelContext:
    travel_km: float
    timezone_shift_hours: float
    days_rest: float
    consecutive_game_days: float
    doubleheader: float


@dataclass(frozen=True)
class UmpireContext:
    assignment_known: float
    called_strike_delta: float
    bb_rate_delta: float
    run_rate_delta: float
    prior_pitches: float


@dataclass(frozen=True)
class CatcherContext:
    catcher_known: float
    framing_runs_per_1000: float
    strike_rate_delta: float
    prior_called_pitches: float


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise V7ContextError(f"invalid {field}") from exc
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise V7ContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _num(value: Any, field: str, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise V7ContextError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise V7ContextError(f"{field} must be numeric") from exc
    if not isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise V7ContextError(f"{field} outside allowed range")
    return x


def park_context(row: Mapping[str, Any]) -> ParkContext:
    try:
        venue_id = int(row["venue_id"])
    except Exception as exc:
        raise V7ContextError("park venue_id required") from exc
    if venue_id <= 0:
        raise V7ContextError("park venue_id invalid")
    return ParkContext(
        venue_id=venue_id,
        run_factor=_num(row.get("run_factor"), "run_factor", lo=.5, hi=1.5),
        hr_factor_lhb=_num(row.get("hr_factor_lhb"), "hr_factor_lhb", lo=.5, hi=1.8),
        hr_factor_rhb=_num(row.get("hr_factor_rhb"), "hr_factor_rhb", lo=.5, hi=1.8),
    )


def weather_context(row: Mapping[str, Any], *, as_of: Any) -> WeatherContext:
    asof = _utc(as_of, "as_of")
    issued = _utc(row.get("issued_at"), "issued_at")
    valid = _utc(row.get("valid_at"), "valid_at")
    if issued > asof:
        raise V7ContextError("weather forecast issued after feature as-of")
    if valid < asof:
        raise V7ContextError("weather forecast already expired for game context")
    wind = _num(row.get("wind_mph"), "wind_mph", lo=0, hi=100)
    component = _num(row.get("wind_out_to_center_mph", 0), "wind_out_to_center_mph", lo=-100, hi=100)
    if abs(component) > wind + 1e-9:
        raise V7ContextError("wind component exceeds wind speed")
    return WeatherContext(
        temperature_f=_num(row.get("temperature_f"), "temperature_f", lo=-20, hi=140),
        humidity_pct=_num(row.get("humidity_pct"), "humidity_pct", lo=0, hi=100),
        pressure_hpa=_num(row.get("pressure_hpa"), "pressure_hpa", lo=850, hi=1100),
        wind_mph=wind,
        wind_out_to_center_mph=component,
        precip_probability=_num(row.get("precip_probability", 0), "precip_probability", lo=0, hi=1),
        roof_closed=float(bool(row.get("roof_closed", False))),
    )


def haversine_km(a_lat: Any, a_lon: Any, b_lat: Any, b_lon: Any) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (
        _num(a_lat, "a_lat", lo=-90, hi=90), _num(a_lon, "a_lon", lo=-180, hi=180),
        _num(b_lat, "b_lat", lo=-90, hi=90), _num(b_lon, "b_lon", lo=-180, hi=180),
    ))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return EARTH_RADIUS_KM * 2 * atan2(sqrt(h), sqrt(max(0.0, 1-h)))


def travel_context(row: Mapping[str, Any]) -> TravelContext:
    travel = haversine_km(row["previous_lat"], row["previous_lon"], row["current_lat"], row["current_lon"])
    return TravelContext(
        travel_km=travel,
        timezone_shift_hours=_num(row.get("timezone_shift_hours", 0), "timezone_shift_hours", lo=-12, hi=12),
        days_rest=_num(row.get("days_rest", 0), "days_rest", lo=0, hi=30),
        consecutive_game_days=_num(row.get("consecutive_game_days", 0), "consecutive_game_days", lo=0, hi=30),
        doubleheader=float(bool(row.get("doubleheader", False))),
    )


def umpire_context(row: Mapping[str, Any] | None) -> UmpireContext:
    if not row:
        return UmpireContext(0.0, 0.0, 0.0, 0.0, 0.0)
    prior = _num(row.get("prior_pitches", 0), "prior_pitches", lo=0)
    if prior <= 0:
        return UmpireContext(1.0, 0.0, 0.0, 0.0, 0.0)
    return UmpireContext(
        assignment_known=1.0,
        called_strike_delta=_num(row.get("called_strike_delta", 0), "called_strike_delta", lo=-.2, hi=.2),
        bb_rate_delta=_num(row.get("bb_rate_delta", 0), "bb_rate_delta", lo=-.2, hi=.2),
        run_rate_delta=_num(row.get("run_rate_delta", 0), "run_rate_delta", lo=-5, hi=5),
        prior_pitches=prior,
    )


def catcher_context(row: Mapping[str, Any] | None) -> CatcherContext:
    if not row:
        return CatcherContext(0.0, 0.0, 0.0, 0.0)
    prior = _num(row.get("prior_called_pitches", 0), "prior_called_pitches", lo=0)
    if prior <= 0:
        return CatcherContext(1.0, 0.0, 0.0, 0.0)
    return CatcherContext(
        catcher_known=1.0,
        framing_runs_per_1000=_num(row.get("framing_runs_per_1000", 0), "framing_runs_per_1000", lo=-50, hi=50),
        strike_rate_delta=_num(row.get("strike_rate_delta", 0), "strike_rate_delta", lo=-.2, hi=.2),
        prior_called_pitches=prior,
    )


def build_v7_environment_context(*, as_of: Any, park: Mapping[str, Any], weather: Mapping[str, Any], travel: Mapping[str, Any], umpire: Mapping[str, Any] | None, catcher: Mapping[str, Any] | None) -> dict[str, Any]:
    asof = _utc(as_of, "as_of")
    payload = {
        "feature_contract_version": V7_CONTEXT_CONTRACT_VERSION,
        "feature_as_of_utc": asof.isoformat(),
        "park": asdict(park_context(park)),
        "weather": asdict(weather_context(weather, as_of=asof)),
        "travel": asdict(travel_context(travel)),
        "umpire": asdict(umpire_context(umpire)),
        "catcher": asdict(catcher_context(catcher)),
    }
    assert_no_market_contamination(payload)
    payload["feature_contract_sha256"] = canonical_json_sha256(payload)
    return payload
