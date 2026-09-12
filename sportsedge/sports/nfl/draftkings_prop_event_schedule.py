"""DraftKings NFL event kickoff binding for prospective prop capture.

This module reuses the research-only NFL DraftKings transport but keeps event
schedule identity separate from quote parsing. No schedule inference is allowed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from .draftkings_prop_source import (
    DK_HOME,
    DraftKingsNFLPropSourceError,
    _discover,
    _json,
    _request,
)


class DraftKingsNFLEventScheduleError(RuntimeError):
    pass


def _iso_utc(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise DraftKingsNFLEventScheduleError("DK_NFL_EVENT_START_MISSING")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DraftKingsNFLEventScheduleError("DK_NFL_EVENT_START_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DraftKingsNFLEventScheduleError("DK_NFL_EVENT_START_NAIVE")
    return dt.astimezone(timezone.utc).isoformat()


def parse_nfl_event_starts(league_payload: Mapping[str, Any]) -> dict[str, str]:
    events = league_payload.get("events")
    if not isinstance(events, list):
        raise DraftKingsNFLEventScheduleError("DK_NFL_LEAGUE_EVENTS_MISSING")
    out: dict[str, str] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        raw_start = None
        for key in ("startDate", "startTime", "startDateTime", "eventStartDate"):
            if event.get(key) not in (None, ""):
                raw_start = event.get(key)
                break
        if raw_start is None:
            continue
        start = _iso_utc(raw_start)
        prior = out.get(event_id)
        if prior is not None and prior != start:
            raise DraftKingsNFLEventScheduleError(f"DK_NFL_EVENT_START_CONFLICT:{event_id}")
        out[event_id] = start
    return out


def fetch_nfl_event_starts(*, opener: Callable = urlopen) -> dict[str, str]:
    try:
        home = _request(DK_HOME, opener=opener).decode("utf-8", errors="replace")
        base, league_id = _discover(home)
        league = _json(f"{base}v1/leagues/{league_id}", opener=opener)
    except DraftKingsNFLPropSourceError as exc:
        raise DraftKingsNFLEventScheduleError(str(exc)) from exc
    if not isinstance(league, Mapping):
        raise DraftKingsNFLEventScheduleError("DK_NFL_LEAGUE_PAYLOAD_INVALID")
    return parse_nfl_event_starts(league)
