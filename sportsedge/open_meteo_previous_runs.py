"""Open-Meteo Previous Runs API: lead-time-labelled past forecasts (research only).

The regular forecast API only shows the newest run, so a backtest that uses it
leaks future information. The Previous Runs API returns, for each hour, the
value forecast N days earlier (``<var>_previous_dayN``). That makes a weather
input point-in-time *by lead time*: a ``previous_day1`` value was available no
later than ``valid_time - 24h``.

This is a lead-time label, not an exact model-run issue time. Records say so
(``availability = LEAD_TIME_BOUND``) and never claim ``historical_pit=true``.
Data: Open-Meteo, CC BY 4.0. Never a pricing input without separate review.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping
from urllib.parse import urlencode

ROOT = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = ("temperature_2m", "wind_speed_10m", "wind_gusts_10m", "precipitation")
SCHEMA = "sportsedge.open_meteo_previous_runs.v1"


class PreviousRunsError(ValueError):
    pass


def _coord(value: Any, lo: float, hi: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not lo <= value <= hi:
        raise PreviousRunsError(f"COORDINATE_INVALID:{name}")
    return float(value)


def previous_runs_url(lat: float, lon: float, valid: datetime, lead_days: int = 1) -> str:
    if valid.tzinfo is None:
        raise PreviousRunsError("VALID_TIME_TZ_REQUIRED")
    if not isinstance(lead_days, int) or isinstance(lead_days, bool) or not 1 <= lead_days <= 7:
        raise PreviousRunsError(f"LEAD_DAYS_INVALID:{lead_days}")
    day = valid.astimezone(timezone.utc).date().isoformat()
    hourly = ",".join(f"{v}_previous_day{lead_days}" for v in VARIABLES)
    return ROOT + "?" + urlencode({
        "latitude": _coord(lat, -90, 90, "lat"), "longitude": _coord(lon, -180, 180, "lon"),
        "hourly": hourly, "start_date": day, "end_date": day,
        "timezone": "UTC", "wind_speed_unit": "mph", "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
    })


def hour_record(payload: Mapping[str, Any], valid: datetime, lead_days: int, *,
                decision_time: datetime | None = None) -> dict[str, Any]:
    """Pick the hour ``valid`` (UTC, on the hour) from a Previous Runs response.

    If ``decision_time`` is given, the lead must be long enough that the value
    was available by then, else ``LEAD_TOO_SHORT_FOR_DECISION`` (fail closed).
    """
    if valid.tzinfo is None:
        raise PreviousRunsError("VALID_TIME_TZ_REQUIRED")
    utc = valid.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    available_by = utc - timedelta(days=lead_days)
    if decision_time is not None:
        if decision_time.tzinfo is None:
            raise PreviousRunsError("DECISION_TIME_TZ_REQUIRED")
        if available_by > decision_time:
            raise PreviousRunsError("LEAD_TOO_SHORT_FOR_DECISION")
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    key = utc.strftime("%Y-%m-%dT%H:%M")
    if times.count(key) != 1:
        raise PreviousRunsError(f"HOUR_MISSING_OR_DUPLICATE:{key}")
    i = times.index(key)
    values: dict[str, float | None] = {}
    for var in VARIABLES:
        series = hourly.get(f"{var}_previous_day{lead_days}")
        if not isinstance(series, list) or len(series) != len(times):
            raise PreviousRunsError(f"SERIES_MISSING:{var}")
        v = series[i]
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)):
            raise PreviousRunsError(f"VALUE_INVALID:{var}")
        values[var] = None if v is None else float(v)
    return {
        "schema": SCHEMA, "valid_time_utc": utc.isoformat(), "lead_days": lead_days,
        "available_no_later_than_utc": available_by.isoformat(),
        "availability": "LEAD_TIME_BOUND", "historical_pit": False,
        "values": values, "attribution": "Open-Meteo, CC BY 4.0",
    }
