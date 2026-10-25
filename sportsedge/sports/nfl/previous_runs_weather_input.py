"""Research-only NFL game weather from Open-Meteo Previous Runs.

Lead-time bound is not an exact forecast issuance receipt. Never feed pricing.
Run: python -m sportsedge.sports.nfl.previous_runs_weather_input --game-id ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from sportsedge.open_meteo_previous_runs import (
    PreviousRunsError, hour_record, previous_runs_url,
)

SCHEMA = "sportsedge.nfl.previous_runs_weather_input.v1"


class WeatherInputError(ValueError):
    pass


def _utc(raw: str | datetime, label: str) -> datetime:
    try:
        stamp = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise WeatherInputError(f"{label}_INVALID") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise WeatherInputError(f"{label}_OFFSET_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "SportsEdge-research/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=20) as response:
        return response.read()


def capture_nfl_weather(*, game_id: str, kickoff: str | datetime,
                        decision_at: str | datetime, latitude: float,
                        longitude: float, lead_days: int = 1,
                        fetch: Callable[[str], bytes] = _fetch,
                        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Fetch unmodified source bytes and emit a hashed, PIT-bounded sidecar.

    Historical fetch time is NOT conflated with the old decision time.
    Exact model issuance is unknown; historical_pit stays False.
    """
    gid = str(game_id).strip()
    if not gid:
        raise WeatherInputError("GAME_ID_REQUIRED")
    start = _utc(kickoff, "KICKOFF")
    decision = _utc(decision_at, "DECISION")
    if decision >= start:
        raise WeatherInputError("DECISION_NOT_PREGAME")
    hour = start.replace(minute=0, second=0, microsecond=0)
    try:
        url = previous_runs_url(latitude, longitude, hour, lead_days)
        raw = fetch(url)
        fetched = _utc(clock(), "FETCHED_AT")
        if not isinstance(raw, bytes) or not raw or len(raw) > 2_000_000:
            raise WeatherInputError("SOURCE_BYTES_INVALID")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("error"):
            raise WeatherInputError("SOURCE_PAYLOAD_INVALID")
        record = hour_record(payload, hour, lead_days, decision_time=decision)
    except WeatherInputError:
        raise
    except (PreviousRunsError, ValueError, TypeError, OSError) as exc:
        raise WeatherInputError(f"SOURCE_REFUSED:{type(exc).__name__}:{exc}") from exc
    available = _utc(record["available_no_later_than_utc"], "AVAILABLE")
    if fetched < available:
        raise WeatherInputError("FETCH_BEFORE_FORECAST_AVAILABLE")
    values = record["values"]
    if any(values.get(k) is None for k in ("temperature_2m", "wind_speed_10m", "wind_gusts_10m", "precipitation")):
        raise WeatherInputError("WEATHER_INCOMPLETE")
    if values["wind_speed_10m"] < 0 or values["wind_gusts_10m"] < 0 or values["precipitation"] < 0:
        raise WeatherInputError("WEATHER_RANGE_INVALID")
    return {
        "schema": SCHEMA, "sport": "NFL", "game_id": gid,
        "kickoff_utc": start.isoformat(), "decision_utc": decision.isoformat(),
        "forecast_valid_hour_utc": hour.isoformat(),
        "source": "OPEN_METEO_PREVIOUS_RUNS", "source_url": url,
        "source_fetched_at_utc": fetched.isoformat(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "forecast_availability": "LEAD_TIME_BOUND_NOT_EXACT_ISSUANCE",
        "available_no_later_than_utc": available.isoformat(),
        "lead_days": lead_days, "historical_pit": False,
        "weather": {"temperature_f": values["temperature_2m"],
                    "wind_mph": values["wind_speed_10m"],
                    "wind_gust_mph": values["wind_gusts_10m"],
                    "precipitation_in": values["precipitation"]},
        "attribution": "Open-Meteo, CC BY 4.0",
        "pricing_input": False, "play_eligible": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game-id", required=True)
    p.add_argument("--kickoff", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--lead-days", type=int, default=1)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        result = capture_nfl_weather(game_id=a.game_id, kickoff=a.kickoff,
                                     decision_at=a.decision, latitude=a.lat,
                                     longitude=a.lon, lead_days=a.lead_days)
    except WeatherInputError as exc:
        p.exit(2, f"REFUSED: {exc}\n")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"NFL_RESEARCH_WEATHER_SIDECAR:{a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
