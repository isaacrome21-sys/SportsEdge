"""Ingest externally fetched MLB historical-event-odds responses into replay archive.

Network credentials are intentionally outside this module. The ingester validates an
exact request descriptor, binds the raw provider response to its provider timestamp
and event identity, and writes the immutable archive contract consumed by the 38-market
replay orchestrator. It never edits timestamps or reconstructs missing quotes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .historical_event_request_plan import canonical_plan_sha256

ARCHIVE_SCHEMA = "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1"
ARCHIVE_SOURCE = "THE_ODDS_API_HISTORICAL"


class MLBHistoricalSnapshotIngestError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise MLBHistoricalSnapshotIngestError(f"{field}_REQUIRED")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBHistoricalSnapshotIngestError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBHistoricalSnapshotIngestError(f"{field}_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLBHistoricalSnapshotIngestError("PROVIDER_RESPONSE_JSON_INVALID") from exc
    if not isinstance(value, Mapping):
        raise MLBHistoricalSnapshotIngestError("PROVIDER_RESPONSE_MAPPING_REQUIRED")
    return value


def _event(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = payload.get("data")
    if isinstance(raw, Mapping):
        events = [raw]
    elif isinstance(raw, list):
        events = [row for row in raw if isinstance(row, Mapping)]
    else:
        raise MLBHistoricalSnapshotIngestError("PROVIDER_EVENT_DATA_REQUIRED")
    if len(events) != 1:
        raise MLBHistoricalSnapshotIngestError(f"PROVIDER_EVENT_COUNT_INVALID:{len(events)}")
    return events[0]


def _request_sha256(request_descriptor: Mapping[str, Any]) -> str:
    encoded = json.dumps(request_descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_request_descriptor(request_descriptor: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request_descriptor, Mapping):
        raise MLBHistoricalSnapshotIngestError("REQUEST_DESCRIPTOR_MAPPING_REQUIRED")
    request_id = str(request_descriptor.get("request_id") or "").strip()
    kind = str(request_descriptor.get("kind") or "").strip().upper()
    canonical_market = str(request_descriptor.get("canonical_market") or "").strip().upper()
    provider_market = str(request_descriptor.get("provider_market") or "").strip()
    requested_at = _iso(_dt(request_descriptor.get("requested_at"), "requested_at"))
    if not request_id or kind not in {"DECISION", "CLOSE"} or not canonical_market or not provider_market:
        raise MLBHistoricalSnapshotIngestError("REQUEST_DESCRIPTOR_IDENTITY_INCOMPLETE")
    query = request_descriptor.get("query_without_api_key")
    if not isinstance(query, Mapping) or str(query.get("markets") or "").strip() != provider_market:
        raise MLBHistoricalSnapshotIngestError("REQUEST_DESCRIPTOR_PROVIDER_MARKET_MISMATCH")
    if "apiKey" in query or "api_key" in query:
        raise MLBHistoricalSnapshotIngestError("REQUEST_DESCRIPTOR_CREDENTIAL_FORBIDDEN")
    event_id = str(request_descriptor.get("event_id") or "").strip() or None
    identity = request_descriptor.get("event_identity")
    if event_id is None and not isinstance(identity, Mapping):
        raise MLBHistoricalSnapshotIngestError("REQUEST_DESCRIPTOR_EVENT_LOCATOR_REQUIRED")
    return {
        **dict(request_descriptor),
        "request_id": request_id,
        "kind": kind,
        "canonical_market": canonical_market,
        "provider_market": provider_market,
        "requested_at": requested_at,
        "event_id": event_id,
    }


def ingest_historical_event_response(
    raw_bytes: bytes, *, request_descriptor: Mapping[str, Any], archive_root: Path,
    plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise MLBHistoricalSnapshotIngestError("RAW_PROVIDER_BYTES_REQUIRED")
    raw = bytes(raw_bytes)
    request = validate_request_descriptor(request_descriptor)
    payload = _payload(raw)
    requested_ts = _dt(request["requested_at"], "requested_at")
    provider_ts = _dt(payload.get("timestamp"), "provider.timestamp")
    if provider_ts > requested_ts:
        raise MLBHistoricalSnapshotIngestError("PROVIDER_TIMESTAMP_AFTER_REQUEST")
    event = _event(payload)
    actual_event_id = str(event.get("id") or "").strip()
    if not actual_event_id:
        raise MLBHistoricalSnapshotIngestError("PROVIDER_EVENT_ID_REQUIRED")
    if request["event_id"] is not None and actual_event_id != request["event_id"]:
        raise MLBHistoricalSnapshotIngestError("PROVIDER_EVENT_ID_MISMATCH")
    identity = request.get("event_identity")
    if isinstance(identity, Mapping):
        expected_home = str(identity.get("home_team") or "").strip()
        expected_away = str(identity.get("away_team") or "").strip()
        expected_start = _iso(_dt(identity.get("commence_time"), "event_identity.commence_time"))
        actual_start = _iso(_dt(event.get("commence_time"), "event.commence_time"))
        if (
            str(event.get("home_team") or "").strip() != expected_home
            or str(event.get("away_team") or "").strip() != expected_away
            or actual_start != expected_start
        ):
            raise MLBHistoricalSnapshotIngestError("PROVIDER_EVENT_IDENTITY_MISMATCH")

    requested_market = request["provider_market"]
    returned_market_keys: set[str] = set()
    books = event.get("bookmakers")
    if books is not None:
        if not isinstance(books, list):
            raise MLBHistoricalSnapshotIngestError("PROVIDER_BOOKMAKERS_LIST_REQUIRED")
        for book in books:
            if not isinstance(book, Mapping):
                raise MLBHistoricalSnapshotIngestError("PROVIDER_BOOK_MAPPING_REQUIRED")
            markets = book.get("markets")
            if markets is None:
                continue
            if not isinstance(markets, list):
                raise MLBHistoricalSnapshotIngestError("PROVIDER_MARKETS_LIST_REQUIRED")
            for market in markets:
                if not isinstance(market, Mapping):
                    raise MLBHistoricalSnapshotIngestError("PROVIDER_MARKET_MAPPING_REQUIRED")
                key = str(market.get("key") or "").strip()
                if key:
                    returned_market_keys.add(key)
    unexpected = sorted(returned_market_keys - {requested_market})
    if unexpected:
        raise MLBHistoricalSnapshotIngestError(f"PROVIDER_UNEXPECTED_MARKETS:{','.join(unexpected)}")

    raw_sha = sha256(raw).hexdigest()
    directory = Path(archive_root) / request["request_id"]
    raw_path = directory / "snapshot.json"
    meta_path = directory / "snapshot.meta.json"
    if raw_path.exists() or meta_path.exists():
        raise MLBHistoricalSnapshotIngestError(f"ARCHIVE_PATH_ALREADY_EXISTS:{directory}")
    directory.mkdir(parents=True, exist_ok=False)
    raw_path.write_bytes(raw)
    metadata = {
        "schema": ARCHIVE_SCHEMA,
        "source": ARCHIVE_SOURCE,
        "request_kind": f"HISTORICAL_EVENT_ODDS_{request['kind']}",
        "request_id": request["request_id"],
        "request_descriptor_sha256": _request_sha256(request_descriptor),
        "request_plan_sha256": canonical_plan_sha256(plan) if plan is not None else None,
        "requested_at": request["requested_at"],
        "provider_timestamp": _iso(provider_ts),
        "event_id": actual_event_id,
        "canonical_market": request["canonical_market"],
        "provider_market": requested_market,
        "returned_market_keys": sorted(returned_market_keys),
        "payload_sha256": raw_sha,
        "interpolated": False,
        "reconstructed": False,
        "promotion_authority": False,
        "may_change_market_eligibility": False,
    }
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "ARCHIVED",
        "archive_dir": str(directory),
        "payload_sha256": raw_sha,
        "provider_timestamp": metadata["provider_timestamp"],
        "event_id": actual_event_id,
        "canonical_market": request["canonical_market"],
        "returned_market_available": requested_market in returned_market_keys,
        "promotion_authority": False,
    }
