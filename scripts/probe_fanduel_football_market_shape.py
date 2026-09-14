#!/usr/bin/env python3
"""Freeze the live response shape needed for a direct FanDuel NFL normalizer.

This is a one-shot, read-only, zero-authority probe. It fetches FanDuel's NFL
managed content page, deterministically selects the first provider-ordered
upcoming two-team event with a usable event id, then fetches that event's full
sportsbook event page. Exact raw bytes are persisted for both requests so a
normalizer can be written against the observed live provider shape instead of
an inferred fixture.

No wager-placement endpoint is used. No Model_P, Truth Gate, promotion,
eligibility, staking, OFFICIAL, registry, evidence-clock, or wager-placement
authority is created by this probe.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from scripts.probe_direct_market_feeds import (
    FANDUEL_ROOT,
    FANDUEL_WEB_KEY,
    DirectMarketProbeError,
    _authority,
    _fetch,
    _persist_raw,
    _shape,
)

UTC = timezone.utc
SELECTION_RULE = "FIRST_PROVIDER_ORDERED_UPCOMING_FANDUEL_NFL_TWO_TEAM_EVENT"


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _event_id(item: Mapping[str, Any]) -> int | None:
    for key in ("eventId", "id"):
        value = item.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _event_start(item: Mapping[str, Any]) -> datetime | None:
    for key in ("openDate", "startTime", "startDate", "eventStartTime"):
        parsed = _parse_ts(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _event_name(item: Mapping[str, Any]) -> str:
    for key in ("name", "eventName", "title"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_upcoming_two_team_event(item: Mapping[str, Any], *, now: datetime) -> bool:
    if _event_id(item) is None:
        return False
    start = _event_start(item)
    if start is None or start <= now:
        return False

    # Content-page event objects have changed field names over time. Discovery
    # stays conservative: require an explicit two-side event name rather than
    # inferring teams from unrelated attachment records.
    name = _event_name(item).lower()
    return any(sep in name for sep in (" @ ", " v ", " vs ", " at "))


def _extract_events(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise DirectMarketProbeError("FANDUEL_NFL_CONTENT_PAGE_NOT_OBJECT")
    attachments = payload.get("attachments")
    if not isinstance(attachments, Mapping):
        raise DirectMarketProbeError("FANDUEL_NFL_ATTACHMENTS_MISSING")
    events = attachments.get("events")
    if isinstance(events, Mapping):
        candidates = list(events.values())
    elif isinstance(events, list):
        candidates = events
    else:
        raise DirectMarketProbeError("FANDUEL_NFL_EVENTS_MISSING")
    return [item for item in candidates if isinstance(item, Mapping)]


def _first_upcoming_event(payload: Any, *, now: datetime) -> Mapping[str, Any]:
    for item in _extract_events(payload):
        if _is_upcoming_two_team_event(item, now=now):
            return item
    raise DirectMarketProbeError("FANDUEL_NFL_NO_UPCOMING_TWO_TEAM_EVENT")


def _content_page_url() -> str:
    query = urlencode(
        {
            "_ak": FANDUEL_WEB_KEY,
            "page": "CUSTOM",
            "customPageId": "nfl",
            "timezone": "America/New_York",
        }
    )
    return f"{FANDUEL_ROOT}/sbapi/content-managed-page?{query}"


def _event_page_url(event_id: int) -> str:
    query = urlencode({"_ak": FANDUEL_WEB_KEY, "eventId": event_id})
    return f"{FANDUEL_ROOT}/sbapi/event-page?{query}"


def probe(
    *,
    out_dir: Path,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> dict[str, Any]:
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "contract": "FANDUEL_FOOTBALL_MARKET_SHAPE_PROBE_V1",
        "state": "BLOCKED",
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "selection_rule": SELECTION_RULE,
        "authority": _authority(),
        "captures": {},
    }

    try:
        raw, payload, status, content_type = _fetch(
            _content_page_url(), provider="fanduel", opener=opener
        )
        report["captures"]["content_page"] = {
            "http_status": status,
            "content_type": content_type,
            **_persist_raw(out_dir, "fanduel", "nfl-content-page", raw),
            "shape": _shape(payload),
        }
        selected = _first_upcoming_event(payload, now=captured_at)
        event_id = _event_id(selected)
        assert event_id is not None
        report["selected_event"] = {
            "event_id": event_id,
            "name": _event_name(selected),
            "start_time": next(
                (
                    selected.get(key)
                    for key in ("openDate", "startTime", "startDate", "eventStartTime")
                    if selected.get(key) is not None
                ),
                None,
            ),
            "item_keys": sorted(str(k) for k in selected.keys()),
        }

        raw, event_page, status, content_type = _fetch(
            _event_page_url(event_id), provider="fanduel", opener=opener
        )
        if not isinstance(event_page, Mapping):
            raise DirectMarketProbeError("FANDUEL_NFL_EVENT_PAGE_NOT_OBJECT")
        attachments = event_page.get("attachments")
        if not isinstance(attachments, Mapping):
            raise DirectMarketProbeError("FANDUEL_NFL_EVENT_PAGE_ATTACHMENTS_MISSING")
        markets = attachments.get("markets")
        if not isinstance(markets, (Mapping, list)) or len(markets) == 0:
            raise DirectMarketProbeError("FANDUEL_NFL_EVENT_PAGE_MARKETS_MISSING")

        report["captures"]["event_page"] = {
            "http_status": status,
            "content_type": content_type,
            **_persist_raw(out_dir, "fanduel", "nfl-event-page", raw),
            "shape": _shape(event_page),
            "attachments_keys": sorted(str(k) for k in attachments.keys()),
            "market_container_type": type(markets).__name__,
            "market_count": len(markets),
        }
        layout = event_page.get("layout")
        if isinstance(layout, Mapping):
            report["captures"]["event_page"]["layout_keys"] = sorted(
                str(k) for k in layout.keys()
            )
        report["state"] = "REACHABLE"
    except DirectMarketProbeError as exc:
        report["reason"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args(argv)
    report = probe(out_dir=Path(args.out_dir))
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "REACHABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
