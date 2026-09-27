#!/usr/bin/env python3
"""Prospective, model-free CFB pre-kickoff weather + prestart capture.

The collector uses public ESPN CFB scoreboard/summary JSON and, when explicit
venue coordinates are available, Open-Meteo forecasts as prospective sources.
It stores the exact raw response bytes by SHA-256 and appends
normalized observations on the SportsEdge data branch. Missing weather is a
recorded miss, never imputed. No Model_P, Truth-Gate, promotion or staking
authority is created here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from sportsedge.public_weather_forecast import forecast_url, kickoff_hour_forecast

UTC = timezone.utc
SCOREBOARD_ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
SUMMARY_ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
SCHEMA_VERSION = "CFB_PIT_WEATHER_OBSERVATION_V1"
WINDOW_PRIORITY = ("close", "t0_prestart", "decision")
ESPN_KEYLESS_USER_AGENTS = ("python-requests/2.32", "curl/8.16.0")


class CFBWeatherCaptureError(RuntimeError):
    pass


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise CFBWeatherCaptureError("CFB_WEATHER_TIMESTAMP_MISSING")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBWeatherCaptureError("CFB_WEATHER_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise CFBWeatherCaptureError("CFB_WEATHER_TIMESTAMP_NAIVE")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _default_opener(url: str, timeout: int = 20):
    """Open a public provider URL with ESPN's keyless non-browser UA contract.

    ESPN's public site API can reject custom/browser-shaped user agents with
    HTTP 403 while still accepting ordinary programmatic clients. Rotate only
    across two deterministic non-browser identities, and only after a 403. This
    changes transport identity, not source, payload, evidence clock, or authority.
    """
    last_403: urllib.error.HTTPError | None = None
    for user_agent in ESPN_KEYLESS_USER_AGENTS:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
            last_403 = exc
    assert last_403 is not None
    raise last_403


def _fetch_bytes(url: str, opener: Callable[..., Any], *, pause: Callable[[float], None] = time.sleep) -> bytes:
    for attempt in range(3):
        try:
            with opener(url, timeout=20) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            reason = f"CFB_WEATHER_HTTP_{exc.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            retryable, reason = True, "CFB_WEATHER_TRANSPORT_FAILED"
        except Exception as exc:
            raise CFBWeatherCaptureError("CFB_WEATHER_FETCH_FAILED") from exc
        if not retryable or attempt == 2:
            raise CFBWeatherCaptureError(reason)
        pause(float(attempt + 1))
    raise AssertionError("unreachable")


def _decode(raw: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBWeatherCaptureError("CFB_WEATHER_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CFBWeatherCaptureError("CFB_WEATHER_JSON_OBJECT_REQUIRED")
    return payload


def _persist_raw(out_dir: Path, raw: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    rel = Path("history") / "cfb" / "weather" / "raw" / f"{digest}.json"
    target = out_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise CFBWeatherCaptureError("CFB_WEATHER_RAW_HASH_COLLISION")
    else:
        target.write_bytes(raw)
    return rel.as_posix(), digest


def _load_policy(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("policy_id") != "CLOSING_LINE_ARCHIVE_V1":
        raise CFBWeatherCaptureError("CFB_WEATHER_WINDOW_POLICY_INVALID")
    return payload


def _window_for(start: datetime, now: datetime, policy: Mapping[str, Any]) -> str | None:
    lead = (start - now).total_seconds() / 60.0
    if lead <= 0:
        return None
    windows = policy.get("windows") or {}
    for name in WINDOW_PRIORITY:
        bounds = windows.get(name)
        if isinstance(bounds, dict) and bounds.get("min_minutes_before_start") <= lead <= bounds.get("max_minutes_before_start"):
            return name
    return None


def _competition(event: Mapping[str, Any]) -> Mapping[str, Any]:
    comps = event.get("competitions") or []
    return comps[0] if comps and isinstance(comps[0], dict) else {}


def _status_state(container: Mapping[str, Any]) -> str:
    status = container.get("status") or {}
    type_row = status.get("type") or {}
    return str(type_row.get("state") or "").strip().lower()


def _teams(comp: Mapping[str, Any]) -> tuple[str, str]:
    home = ""
    away = ""
    for item in comp.get("competitors") or []:
        if not isinstance(item, dict):
            continue
        team = item.get("team") or {}
        name = str(team.get("displayName") or team.get("shortDisplayName") or team.get("name") or "").strip()
        if item.get("homeAway") == "home":
            home = name
        elif item.get("homeAway") == "away":
            away = name
    return home, away


def _summary_comp(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    header = summary.get("header") or {}
    comps = header.get("competitions") or []
    return comps[0] if comps and isinstance(comps[0], dict) else {}


def _weather_from(summary: Mapping[str, Any], summary_comp: Mapping[str, Any], scoreboard_comp: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    candidates = [
        (summary_comp.get("weather"), "ESPN_CFB_SUMMARY"),
        ((summary.get("gameInfo") or {}).get("weather"), "ESPN_CFB_SUMMARY"),
        (summary.get("weather"), "ESPN_CFB_SUMMARY"),
        (scoreboard_comp.get("weather"), "ESPN_CFB_SCOREBOARD"),
    ]
    for value, source in candidates:
        if isinstance(value, dict) and value:
            return dict(value), source
    return None, ""


def _append_row(out_dir: Path, row: Mapping[str, Any]) -> str:
    date = str(row["commence_time"])[:10]
    rel = Path("history") / "cfb" / "weather" / f"{date}.ndjson"
    target = out_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
    return rel.as_posix()


def capture_weather(
    *,
    now: datetime,
    policy: Mapping[str, Any],
    out_dir: Path,
    opener: Callable[..., Any] = _default_opener,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    clock = clock or (lambda: datetime.now(UTC))
    if now.tzinfo is None or now.utcoffset() is None:
        raise CFBWeatherCaptureError("CFB_WEATHER_TIMESTAMP_NAIVE")
    captured_at = _iso(now)
    events: dict[str, tuple[Mapping[str, Any], bytes, str]] = {}
    for delta in (0, 1):
        date_text = (now + timedelta(days=delta)).strftime("%Y%m%d")
        url = f"{SCOREBOARD_ROOT}?dates={date_text}&limit=500"
        raw = _fetch_bytes(url, opener)
        payload = _decode(raw)
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "").strip()
            if event_id:
                events[event_id] = (event, raw, url)

    written = 0
    observations: list[str] = []
    skips: list[dict[str, Any]] = []
    for event_id, (event, scoreboard_raw, scoreboard_url) in sorted(events.items()):
        comp = _competition(event)
        try:
            start = _parse_ts(event.get("date") or comp.get("date"))
        except CFBWeatherCaptureError:
            skips.append({"event_id": event_id, "reason": "COMMENCE_TIME_INVALID"})
            continue
        window = _window_for(start, now, policy)
        if window is None:
            continue
        if _status_state(comp) != "pre":
            skips.append({"event_id": event_id, "window": window, "reason": "SCOREBOARD_NOT_PRESTART"})
            continue
        home, away = _teams(comp)
        if not home or not away:
            skips.append({"event_id": event_id, "window": window, "reason": "TEAM_IDENTITY_MISSING"})
            continue

        summary_url = f"{SUMMARY_ROOT}?event={event_id}"
        summary_raw = _fetch_bytes(summary_url, opener)
        summary = _decode(summary_raw)
        received_at = clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None or received_at < now:
            raise CFBWeatherCaptureError("CFB_WEATHER_CAPTURE_CLOCK_INVALID")
        window = _window_for(start, received_at, policy)
        if window is None:
            skips.append({"event_id": event_id, "reason": "RESPONSE_OUTSIDE_PRESTART_WINDOW"})
            continue
        summary_comp = _summary_comp(summary)
        summary_state = _status_state(summary_comp)
        if summary_state and summary_state != "pre":
            skips.append({"event_id": event_id, "window": window, "reason": "SUMMARY_NOT_PRESTART"})
            continue
        weather, source = _weather_from(summary, summary_comp, comp)
        supporting_raw = []
        if weather is None:
            venue = (summary.get("gameInfo") or {}).get("venue") or comp.get("venue") or {}
            location = (venue.get("location") or venue) if isinstance(venue, Mapping) else {}
            if not isinstance(location, Mapping):
                location = {}
            try:
                url = forecast_url(location.get("latitude"), location.get("longitude"), start)
                forecast_raw = _fetch_bytes(url, opener)
                weather = kickoff_hour_forecast(_decode(forecast_raw), start)
            except (ValueError, CFBWeatherCaptureError) as exc:
                skips.append({"event_id": event_id, "window": window, "reason": "WEATHER_NOT_PUBLISHED", "fallback_reason": str(exc)})
                continue
            previous_receipt = received_at
            received_at = clock()
            if received_at.tzinfo is None or received_at.utcoffset() is None or received_at < previous_receipt:
                raise CFBWeatherCaptureError("CFB_WEATHER_CAPTURE_CLOCK_INVALID")
            window = _window_for(start, received_at, policy)
            if window is None:
                skips.append({"event_id": event_id, "reason": "RESPONSE_OUTSIDE_PRESTART_WINDOW"})
                continue
            for raw in (scoreboard_raw, summary_raw):
                path, digest = _persist_raw(out_dir, raw)
                supporting_raw.append({"raw_relative_path": path, "raw_sha256": digest})
            source, source_raw, source_url = "OPEN_METEO_FORECAST", forecast_raw, url
        if source == "ESPN_CFB_SUMMARY":
            source_raw, source_url = summary_raw, summary_url
        elif source == "ESPN_CFB_SCOREBOARD":
            source_raw, source_url = scoreboard_raw, scoreboard_url
        captured_at = _iso(received_at)
        raw_path, raw_sha = _persist_raw(out_dir, source_raw)
        material = f"{event_id}\n{captured_at}\n{window}\n{raw_sha}".encode("utf-8")
        observation_id = hashlib.sha256(material).hexdigest()
        row = {
            "schema_version": SCHEMA_VERSION,
            "sport": "CFB",
            "evidence_class": "PROSPECTIVE_PIT_WEATHER_OBSERVATION",
            "promotion_authority": False,
            "model_p_created": False,
            "retroactive_evidence_allowed": False,
            "source": source,
            "source_uri": source_url,
            "raw_relative_path": raw_path,
            "raw_sha256": raw_sha,
            "observation_id": observation_id,
            "espn_event_id": event_id,
            "home_team": home,
            "away_team": away,
            "commence_time": _iso(start),
            "captured_at_utc": captured_at,
            "scheduled_lead_minutes": round((start - received_at).total_seconds() / 60.0, 6),
            "window": window,
            "status_state": "pre",
            "prestart_attested": True,
            "weather": weather,
            "supporting_raw": supporting_raw,
            "timestamp_semantics": "RESPONSE_RECEIPT_UPPER_BOUND",
        }
        _append_row(out_dir, row)
        written += 1
        observations.append(observation_id)

    return {
        "contract": "SPORTSEDGE_CFB_WEATHER_PIT_CAPTURE_V1",
        "ran_at_utc": _iso(now),
        "event_count": len(events),
        "observations_written": written,
        "observation_ids": observations,
        "skips": skips,
        "retroactive_evidence_allowed": False,
        "promotion_authority": False,
        "model_p_created": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="config/closing_line_archive_policy_v1.json")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--status-out", default=None)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    try:
        if args.now is not None:
            raise CFBWeatherCaptureError("CFB_WEATHER_LIVE_CLOCK_OVERRIDE_PROHIBITED")
        now = datetime.now(UTC)
        policy = _load_policy(Path(args.policy))
        report = capture_weather(now=now, policy=policy, out_dir=Path(args.out_dir))
    except CFBWeatherCaptureError as exc:
        report = {"state": "BLOCKED", "reason": str(exc), "promotion_authority": False}
        code = 2
    else:
        code = 0
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.status_out:
        Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.status_out).write_text(text + "\n", encoding="utf-8")
    print(text, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
