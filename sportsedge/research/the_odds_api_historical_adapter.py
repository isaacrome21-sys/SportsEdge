"""Adapter from The Odds API historical response shape to SportsEdge admission rows.

This module adopts documented source structure only. It does not fetch data or claim evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping
import hashlib
import json

from .historical_price_admission import validate_historical_snapshot


def _utc(value: object, label: str) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"{label} must be ISO8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _request_sha(request_identity: Mapping[str, object]) -> str:
    payload = json.dumps(dict(request_identity), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def adapt_historical_response(
    response: Mapping[str, object],
    *,
    raw_bytes: bytes,
    retrieved_at_utc: str,
    request_identity: Mapping[str, object],
) -> list[dict]:
    """Return admitted paired benchmark rows from one historical API snapshot.

    The documented API returns a top-level snapshot timestamp and a list of events.
    Each bookmaker has its own last_update and markets/outcomes. Every emitted row is
    validated by the SportsEdge fail-closed source-admission contract.
    """
    if not raw_bytes:
        raise ValueError("raw response bytes required")
    snapshot_ts = _utc(response.get("timestamp"), "timestamp")
    retrieved = _utc(retrieved_at_utc, "retrieved_at_utc")
    data = response.get("data")
    if not isinstance(data, list):
        raise ValueError("historical response data must be a list")

    raw_sha = _sha_bytes(raw_bytes)
    req_sha = _request_sha(request_identity)
    out: list[dict] = []
    for event in data:
        if not isinstance(event, Mapping):
            raise ValueError("event must be a mapping")
        event_id = str(event.get("id") or "")
        sport_key = str(event.get("sport_key") or "")
        commence = _utc(event.get("commence_time"), "commence_time")
        if not event_id or not sport_key:
            raise ValueError("event id and sport_key required")
        books = event.get("bookmakers")
        if not isinstance(books, list):
            raise ValueError("bookmakers must be a list")
        for book in books:
            if not isinstance(book, Mapping):
                raise ValueError("bookmaker must be a mapping")
            book_key = str(book.get("key") or "")
            book_title = str(book.get("title") or "")
            last_update = _utc(book.get("last_update"), "bookmaker.last_update")
            if not book_key or not book_title:
                raise ValueError("bookmaker key/title required")
            markets = book.get("markets")
            if not isinstance(markets, list):
                raise ValueError("markets must be a list")
            for market in markets:
                if not isinstance(market, Mapping):
                    raise ValueError("market must be a mapping")
                key = str(market.get("key") or "")
                if key not in {"h2h", "spreads", "totals"}:
                    continue
                row = {
                    "sport_key": sport_key,
                    "event_id": event_id,
                    "commence_time_utc": commence,
                    "snapshot_timestamp_utc": snapshot_ts,
                    "book_key": book_key,
                    "book_title": book_title,
                    "book_last_update_utc": last_update,
                    "market_key": key,
                    "outcomes": market.get("outcomes"),
                    "raw_byte_sha256": raw_sha,
                    "retrieved_at_utc": retrieved,
                    "source_request_sha256": req_sha,
                }
                out.append(validate_historical_snapshot(row))
    return out
