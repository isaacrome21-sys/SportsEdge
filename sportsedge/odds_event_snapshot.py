"""Shared, immutable The Odds API MLB event snapshot with explicit provenance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .odds_api_source import SPORT_KEY, OddsApiSourceError, _event_url, _get_json


@dataclass(frozen=True)
class OddsEventSnapshot:
    provider: str
    source_path: str
    acquired_at_utc: datetime
    payload_sha256: str
    events: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if self.provider != "THE_ODDS_API":
            raise ValueError("ODDS_EVENT_SNAPSHOT_PROVIDER_INVALID")
        if self.source_path != f"/sports/{SPORT_KEY}/events":
            raise ValueError("ODDS_EVENT_SNAPSHOT_SOURCE_PATH_INVALID")
        if self.acquired_at_utc.tzinfo is None or self.acquired_at_utc.utcoffset() is None:
            raise ValueError("ODDS_EVENT_SNAPSHOT_TIMEZONE_REQUIRED")
        if len(self.payload_sha256) != 64:
            raise ValueError("ODDS_EVENT_SNAPSHOT_HASH_INVALID")

    def provenance_fields(self) -> dict[str, Any]:
        return {
            "provider_event_snapshot_provider": self.provider,
            "provider_event_snapshot_source_path": self.source_path,
            "provider_event_snapshot_acquired_at": self.acquired_at_utc.astimezone(timezone.utc),
            "provider_event_snapshot_sha256": self.payload_sha256,
        }

    def event_by_id(self, provider_event_id: str) -> Mapping[str, Any]:
        matches = [e for e in self.events if str(e.get("id") or "").strip() == provider_event_id]
        if len(matches) != 1:
            raise OddsApiSourceError(
                "ODDS_EVENT_SNAPSHOT_EVENT_NOT_FOUND"
                if not matches
                else "ODDS_EVENT_SNAPSHOT_EVENT_AMBIGUOUS"
            )
        return matches[0]


def _canonical_payload_bytes(payload: Iterable[Mapping[str, Any]]) -> bytes:
    return json.dumps(
        list(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def acquire_mlb_event_snapshot(
    *,
    api_key: str,
    opener: Callable = urlopen,
    acquired_at: datetime | None = None,
) -> OddsEventSnapshot:
    url = _event_url(f"/sports/{SPORT_KEY}/events", api_key=api_key)
    payload = _get_json(url, opener=opener, label="events:shared")
    if not isinstance(payload, list):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")
    events = tuple(x for x in payload if isinstance(x, Mapping))
    if len(events) != len(payload):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_CONTAINS_NON_OBJECT")
    raw = _canonical_payload_bytes(events)
    stamp = acquired_at or datetime.now(timezone.utc)
    return OddsEventSnapshot(
        provider="THE_ODDS_API",
        source_path=f"/sports/{SPORT_KEY}/events",
        acquired_at_utc=stamp.astimezone(timezone.utc),
        payload_sha256=hashlib.sha256(raw).hexdigest(),
        events=events,
    )
