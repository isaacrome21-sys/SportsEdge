#!/usr/bin/env python3
"""Append-only DraftKings MLB prop PIT archive for validation challengers.

This lane is evidence collection, not model execution. It persists the actual
pregame quote rows needed to validate PITCHER_OUTS, PITCHER_ER and RBI without
turning provider-probe summaries into fake historical evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from sportsedge.draftkings_prop_source import fetch_mlb_prop_quotes, _json

TARGET_MARKETS = {"PITCHER_OUTS", "PITCHER_ER", "RBI"}
EVENT_TIME_KEYS = ("startDate", "startDateTime", "startTime", "commenceTime", "commence_time")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _event_first_pitch(event: Mapping[str, Any]) -> datetime | None:
    for key in EVENT_TIME_KEYS:
        dt = _parse_iso(event.get(key))
        if dt is not None:
            return dt
    # Some provider payloads nest time metadata.
    for container_key in ("event", "metadata", "schedule"):
        nested = event.get(container_key)
        if isinstance(nested, Mapping):
            for key in EVENT_TIME_KEYS:
                dt = _parse_iso(nested.get(key))
                if dt is not None:
                    return dt
    return None


def _event_name(event: Mapping[str, Any]) -> str:
    for key in ("name", "eventName", "displayName"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _event_index(base_url: str, league_id: int) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    payload = _json(f"{base_url}v1/leagues/{league_id}")
    events = payload.get("events") if isinstance(payload, Mapping) else None
    if not isinstance(events, list):
        raise RuntimeError("DK_LEAGUE_EVENTS_MISSING_FOR_ARCHIVE")
    index: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        first_pitch = _event_first_pitch(event)
        if first_pitch is None:
            failures.append({"provider_event_id": event_id, "reason": "FIRST_PITCH_MISSING"})
            continue
        index[event_id] = {
            "provider_event_id": event_id,
            "event_name": _event_name(event),
            "first_pitch_at": first_pitch.isoformat(),
        }
    return index, failures


def build_archive_payload(*, now: datetime | None = None) -> dict[str, Any]:
    captured_at = (now or _utcnow()).astimezone(timezone.utc)
    snap = fetch_mlb_prop_quotes()
    if snap.base_url is None or snap.league_id is None:
        raise RuntimeError("DK_PROVIDER_METADATA_MISSING")
    events, event_failures = _event_index(snap.base_url, snap.league_id)

    provider_rows = [dict(row) for row in snap.quotes]
    target_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    market_counts = {market: 0 for market in sorted(TARGET_MARKETS)}

    for quote in provider_rows:
        market = str(quote.get("market") or "").upper()
        if market not in TARGET_MARKETS:
            continue
        event_id = str(quote.get("provider_event_id") or "")
        event = events.get(event_id)
        retrieved = _parse_iso(quote.get("retrieved_at"))
        if event is None:
            rejected_rows.append({
                "market": market,
                "provider_event_id": event_id,
                "entity_name": quote.get("entity_name"),
                "reason": "EVENT_TIME_UNAVAILABLE",
            })
            continue
        first_pitch = _parse_iso(event["first_pitch_at"])
        if retrieved is None or first_pitch is None:
            rejected_rows.append({
                "market": market,
                "provider_event_id": event_id,
                "entity_name": quote.get("entity_name"),
                "reason": "TIMESTAMP_INVALID",
            })
            continue
        if retrieved >= first_pitch:
            rejected_rows.append({
                "market": market,
                "provider_event_id": event_id,
                "entity_name": quote.get("entity_name"),
                "reason": "NOT_PREGAME",
                "quote_retrieved_at": retrieved.isoformat(),
                "first_pitch_at": first_pitch.isoformat(),
            })
            continue
        row = {
            **quote,
            **event,
            "quote_retrieved_at": retrieved.isoformat(),
            "pit_eligible": True,
            "archive_captured_at": captured_at.isoformat(),
        }
        target_rows.append(row)
        market_counts[market] += 1

    payload: dict[str, Any] = {
        "schema_version": 1,
        "archive_type": "MLB_PROP_PIT_QUOTES",
        "provider": "DRAFTKINGS_WEB_RESEARCH",
        "captured_at": captured_at.isoformat(),
        "target_markets": sorted(TARGET_MARKETS),
        "provider_quote_count": len(provider_rows),
        "pit_target_quote_count": len(target_rows),
        "market_counts": market_counts,
        "provider_failure_count": len(snap.failures),
        "event_failure_count": len(event_failures),
        "rejected_target_count": len(rejected_rows),
        "provider_failures": list(snap.failures),
        "event_failures": event_failures,
        "rejected_targets": rejected_rows,
        "quotes": target_rows,
    }
    payload["payload_sha256"] = _sha256_json({k: v for k, v in payload.items() if k != "payload_sha256"})
    return payload


def persist_payload(payload: Mapping[str, Any], *, root: Path = Path("artifacts/prop_odds")) -> tuple[Path, Path]:
    captured = _parse_iso(payload.get("captured_at"))
    if captured is None:
        raise ValueError("captured_at invalid")
    day = captured.date().isoformat()
    stamp = captured.strftime("%Y%m%dT%H%M%S.%fZ")
    immutable = root / day / f"props_{stamp}.json"
    latest = root / "latest.json"
    _atomic_json(immutable, dict(payload))
    _atomic_json(latest, {
        "schema_version": 1,
        "captured_at": captured.isoformat(),
        "payload_sha256": payload.get("payload_sha256"),
        "pit_target_quote_count": payload.get("pit_target_quote_count"),
        "market_counts": payload.get("market_counts"),
        "immutable_file": str(immutable),
    })
    return immutable, latest


def _self_test() -> int:
    assert _parse_iso("2026-08-23T23:00:00Z") == datetime(2026, 8, 23, 23, 0, tzinfo=timezone.utc)
    assert _event_first_pitch({"startDate": "2026-08-24T00:10:00Z"}) == datetime(2026, 8, 24, 0, 10, tzinfo=timezone.utc)
    assert _event_first_pitch({"metadata": {"commenceTime": "2026-08-24T00:10:00+00:00"}}) is not None
    assert _event_first_pitch({"name": "missing"}) is None
    digest = _sha256_json({"a": 1, "b": 2})
    assert len(digest) == 64
    print(json.dumps({"status": "SELF_TEST_OK", "pit_timestamp_guard": "PASS", "hash": "PASS"}))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    try:
        payload = build_archive_payload()
        immutable, latest = persist_payload(payload)
        status = "CAPTURED" if int(payload["pit_target_quote_count"]) > 0 else "BLOCKED_NO_TARGET_QUOTES"
        print(json.dumps({
            "status": status,
            "pit_target_quote_count": payload["pit_target_quote_count"],
            "market_counts": payload["market_counts"],
            "payload_sha256": payload["payload_sha256"],
            "immutable_file": str(immutable),
            "latest_file": str(latest),
        }))
        return 0 if status == "CAPTURED" else 3
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
