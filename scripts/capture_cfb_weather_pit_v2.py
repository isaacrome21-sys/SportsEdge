#!/usr/bin/env python3
"""Prospective CFB pre-kickoff weather capture with fail-closed transport fallback.

This collector preserves the existing CFB weather evidence contract while making
transport identity explicit. It prefers ESPN's site API and may fall back to
ESPN's CDN endpoints when the site transport is blocked. Every admitted row is
bound to the exact response bytes actually used. The transport probe is
non-authoritative and never writes evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlparse

UTC = timezone.utc
SITE_SCOREBOARD_ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
SITE_SUMMARY_ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
CDN_SCOREBOARD_ROOT = "https://cdn.espn.com/core/college-football/scoreboard"
CDN_GAME_ROOT = "https://cdn.espn.com/core/college-football/game"
SCHEMA_VERSION = "CFB_PIT_WEATHER_OBSERVATION_V1"
WINDOW_PRIORITY = ("close", "t0_prestart", "decision")
USER_AGENT = "SportsEdge-CFB-weather-PIT/2 (+https://github.com/isaacrome21-sys/SportsEdge)"
TRANSIENT_HTTP = {429, 500, 502, 503, 504}


class CFBWeatherCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransportFailure:
    source: str
    host: str
    http_status: int | None
    retryable: bool
    reason: str
    server: str = ""
    retry_after: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "host": self.host,
            "http_status": self.http_status,
            "retryable": self.retryable,
            "transport_reason": self.reason,
            "server": self.server,
            "retry_after": self.retry_after,
        }


class CFBWeatherTransportError(CFBWeatherCaptureError):
    def __init__(self, failure: TransportFailure, *, primary_failure: TransportFailure | None = None):
        super().__init__(failure.reason)
        self.failure = failure
        self.primary_failure = primary_failure


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


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )


def _fetch_bytes(
    url: str,
    *,
    source: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    pause: Callable[[float], None] = time.sleep,
) -> bytes:
    host = (urlparse(url).hostname or "").lower()
    for attempt in range(3):
        try:
            with opener(_request(url), timeout=20) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in TRANSIENT_HTTP
            failure = TransportFailure(
                source=source,
                host=host,
                http_status=int(exc.code),
                retryable=retryable,
                reason=f"CFB_WEATHER_HTTP_{exc.code}",
                server=str(exc.headers.get("Server") or "") if exc.headers else "",
                retry_after=str(exc.headers.get("Retry-After") or "") if exc.headers else "",
            )
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            failure = TransportFailure(
                source=source,
                host=host,
                http_status=None,
                retryable=True,
                reason=f"CFB_WEATHER_TRANSPORT_FAILED:{type(exc).__name__}",
            )
            retryable = True
        except Exception as exc:
            failure = TransportFailure(
                source=source,
                host=host,
                http_status=None,
                retryable=False,
                reason=f"CFB_WEATHER_FETCH_FAILED:{type(exc).__name__}",
            )
            raise CFBWeatherTransportError(failure) from exc
        if not retryable or attempt == 2:
            raise CFBWeatherTransportError(failure)
        pause(float(attempt + 1))
    raise AssertionError("unreachable")


def _fetch_with_fallback(
    primary_url: str,
    *,
    primary_source: str,
    fallback_url: str,
    fallback_source: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[bytes, str, str, TransportFailure | None]:
    try:
        raw = _fetch_bytes(primary_url, source=primary_source, opener=opener, pause=pause)
        return raw, primary_source, primary_url, None
    except CFBWeatherTransportError as primary:
        try:
            raw = _fetch_bytes(fallback_url, source=fallback_source, opener=opener, pause=pause)
            return raw, fallback_source, fallback_url, primary.failure
        except CFBWeatherTransportError as fallback:
            raise CFBWeatherTransportError(fallback.failure, primary_failure=primary.failure) from fallback


def _decode(raw: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBWeatherCaptureError("CFB_WEATHER_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CFBWeatherCaptureError("CFB_WEATHER_JSON_OBJECT_REQUIRED")
    return payload


def _site_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise CFBWeatherCaptureError("CFB_WEATHER_SITE_EVENTS_INVALID")
    return [x for x in events if isinstance(x, Mapping)]


def _cdn_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = payload.get("content") or {}
    sb_data = content.get("sbData") if isinstance(content, Mapping) else {}
    events = sb_data.get("events") if isinstance(sb_data, Mapping) else None
    if events is None:
        events = payload.get("events")
    if not isinstance(events, list):
        raise CFBWeatherCaptureError("CFB_WEATHER_CDN_EVENTS_INVALID")
    return [x for x in events if isinstance(x, Mapping)]


def _summary_payload(payload: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    if source == "ESPN_SITE_SUMMARY":
        return payload
    content = payload.get("content") or {}
    if isinstance(content, Mapping):
        game = content.get("gamepackageJSON")
        if isinstance(game, Mapping):
            return game
    game = payload.get("gamepackageJSON")
    if isinstance(game, Mapping):
        return game
    raise CFBWeatherCaptureError("CFB_WEATHER_CDN_GAMEPACKAGE_INVALID")


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
    return comps[0] if comps and isinstance(comps[0], Mapping) else {}


def _status_state(container: Mapping[str, Any]) -> str:
    status = container.get("status") or {}
    type_row = status.get("type") or {}
    return str(type_row.get("state") or "").strip().lower()


def _teams(comp: Mapping[str, Any]) -> tuple[str, str]:
    home = ""
    away = ""
    for item in comp.get("competitors") or []:
        if not isinstance(item, Mapping):
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
    return comps[0] if comps and isinstance(comps[0], Mapping) else {}


def _weather_from(
    summary: Mapping[str, Any],
    summary_comp: Mapping[str, Any],
    scoreboard_comp: Mapping[str, Any],
    summary_source: str,
    scoreboard_source: str,
) -> tuple[dict[str, Any] | None, str]:
    candidates = [
        (summary_comp.get("weather"), summary_source),
        ((summary.get("gameInfo") or {}).get("weather"), summary_source),
        (summary.get("weather"), summary_source),
        (scoreboard_comp.get("weather"), scoreboard_source),
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


def _open_meteo_weather(location: Mapping[str, Any], start: datetime, *, opener: Callable[..., Any], pause: Callable[[float], None]) -> tuple[dict[str, Any], bytes, str]:
    try:
        from sportsedge.public_weather_forecast import forecast_url, kickoff_hour_forecast
    except Exception as exc:
        raise CFBWeatherCaptureError("CFB_WEATHER_OPEN_METEO_HELPER_UNAVAILABLE") from exc
    try:
        url = forecast_url(location.get("latitude"), location.get("longitude"), start)
    except ValueError as exc:
        raise CFBWeatherCaptureError(str(exc)) from exc
    raw = _fetch_bytes(url, source="OPEN_METEO_FORECAST", opener=opener, pause=pause)
    weather = kickoff_hour_forecast(_decode(raw), start)
    return weather, raw, url


def capture_weather(
    *,
    now: datetime,
    policy: Mapping[str, Any],
    out_dir: Path,
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], datetime] | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    clock = clock or (lambda: datetime.now(UTC))
    if now.tzinfo is None or now.utcoffset() is None:
        raise CFBWeatherCaptureError("CFB_WEATHER_TIMESTAMP_NAIVE")
    events: dict[str, tuple[Mapping[str, Any], bytes, str, str]] = {}
    fallback_observed: list[dict[str, Any]] = []
    for delta in (0, 1):
        date_text = (now + timedelta(days=delta)).strftime("%Y%m%d")
        site_url = SITE_SCOREBOARD_ROOT + "?" + urlencode({"dates": date_text, "limit": 500})
        cdn_url = CDN_SCOREBOARD_ROOT + "?" + urlencode({"xhr": 1, "dates": date_text, "limit": 500})
        raw, source, source_url, primary_failure = _fetch_with_fallback(
            site_url,
            primary_source="ESPN_SITE_SCOREBOARD",
            fallback_url=cdn_url,
            fallback_source="ESPN_CDN_SCOREBOARD",
            opener=opener,
            pause=pause,
        )
        if primary_failure:
            fallback_observed.append(primary_failure.as_dict())
        payload = _decode(raw)
        rows = _site_events(payload) if source == "ESPN_SITE_SCOREBOARD" else _cdn_events(payload)
        for event in rows:
            event_id = str(event.get("id") or "").strip()
            if event_id:
                events[event_id] = (event, raw, source_url, source)

    written = 0
    observations: list[str] = []
    skips: list[dict[str, Any]] = []
    for event_id, (event, scoreboard_raw, scoreboard_url, scoreboard_source) in sorted(events.items()):
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

        site_url = SITE_SUMMARY_ROOT + "?" + urlencode({"event": event_id})
        cdn_url = CDN_GAME_ROOT + "?" + urlencode({"xhr": 1, "gameId": event_id})
        summary_raw, summary_source, summary_url, primary_failure = _fetch_with_fallback(
            site_url,
            primary_source="ESPN_SITE_SUMMARY",
            fallback_url=cdn_url,
            fallback_source="ESPN_CDN_GAME",
            opener=opener,
            pause=pause,
        )
        if primary_failure:
            fallback_observed.append(primary_failure.as_dict())
        summary = _summary_payload(_decode(summary_raw), summary_source)
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
        weather, source = _weather_from(summary, summary_comp, comp, summary_source, scoreboard_source)
        supporting_raw: list[dict[str, Any]] = []
        if weather is None:
            venue = (summary.get("gameInfo") or {}).get("venue") or comp.get("venue") or {}
            location = (venue.get("location") or venue) if isinstance(venue, Mapping) else {}
            if not isinstance(location, Mapping):
                location = {}
            try:
                weather, forecast_raw, forecast_url = _open_meteo_weather(location, start, opener=opener, pause=pause)
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
            source, source_raw, source_url = "OPEN_METEO_FORECAST", forecast_raw, forecast_url
        elif source == summary_source:
            source_raw, source_url = summary_raw, summary_url
        else:
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
        "contract": "SPORTSEDGE_CFB_WEATHER_PIT_CAPTURE_V2",
        "ran_at_utc": _iso(now),
        "event_count": len(events),
        "observations_written": written,
        "observation_ids": observations,
        "skips": skips,
        "transport_fallbacks_observed": fallback_observed,
        "retroactive_evidence_allowed": False,
        "promotion_authority": False,
        "model_p_created": False,
    }


def probe_transports(*, opener: Callable[..., Any] = urllib.request.urlopen, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    date_text = now.strftime("%Y%m%d")
    targets = [
        ("ESPN_SITE_SCOREBOARD", SITE_SCOREBOARD_ROOT + "?" + urlencode({"dates": date_text, "limit": 1})),
        ("ESPN_CDN_SCOREBOARD", CDN_SCOREBOARD_ROOT + "?" + urlencode({"xhr": 1, "dates": date_text, "limit": 1})),
    ]
    checks: list[dict[str, Any]] = []
    for source, url in targets:
        try:
            raw = _fetch_bytes(url, source=source, opener=opener, pause=lambda _x: None)
            _decode(raw)
            checks.append({"source": source, "host": urlparse(url).hostname, "ok": True, "bytes": len(raw)})
        except CFBWeatherTransportError as exc:
            checks.append({"source": source, "ok": False, **exc.failure.as_dict()})
        except CFBWeatherCaptureError as exc:
            checks.append({"source": source, "host": urlparse(url).hostname, "ok": False, "transport_reason": str(exc)})
    return {
        "contract": "SPORTSEDGE_CFB_WEATHER_TRANSPORT_PROBE_V1",
        "ran_at_utc": _iso(now),
        "checks": checks,
        "site_ok": next((x["ok"] for x in checks if x["source"] == "ESPN_SITE_SCOREBOARD"), False),
        "cdn_ok": next((x["ok"] for x in checks if x["source"] == "ESPN_CDN_SCOREBOARD"), False),
        "promotion_authority": False,
        "model_p_created": False,
        "evidence_written": False,
    }


def _blocked_report(exc: Exception) -> dict[str, Any]:
    report: dict[str, Any] = {
        "state": "BLOCKED",
        "reason": str(exc),
        "promotion_authority": False,
        "model_p_created": False,
        "evidence_written": False,
    }
    if isinstance(exc, CFBWeatherTransportError):
        report.update(exc.failure.as_dict())
        if exc.primary_failure is not None:
            report["primary_transport_failure"] = exc.primary_failure.as_dict()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="config/closing_line_archive_policy_v1.json")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--status-out", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args(argv)
    if args.now is not None:
        report = _blocked_report(CFBWeatherCaptureError("CFB_WEATHER_LIVE_CLOCK_OVERRIDE_PROHIBITED"))
        code = 2
    elif args.probe_only:
        report = probe_transports()
        code = 0
    else:
        try:
            now = datetime.now(UTC)
            policy = _load_policy(Path(args.policy))
            report = capture_weather(now=now, policy=policy, out_dir=Path(args.out_dir))
        except CFBWeatherCaptureError as exc:
            report = _blocked_report(exc)
            code = 2
        else:
            code = 0
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.status_out:
        Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.status_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
