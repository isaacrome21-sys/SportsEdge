"""Per-game capture-span manifest for parallel DraftKings capture.

The scheduled NBA captures are moving from one long sequential pass over
the board to per-game captures run in parallel. This module is the
repo-side accounting for that change: given one span record per game —
event id, capture start, capture finish — it computes each game's span
and rules on it under the standing capture-freshness ruling:

  - a game's capture span may not exceed 150 seconds (the paired-quote
    span bar; 150.0 is valid, anything above is refused);
  - the 180-second quote-age freshness limit is unchanged and is still
    enforced where quotes are consumed — this manifest neither relaxes
    it nor substitutes for it.

A game over the span limit is REFUSED_SPAN: it stays in the manifest
with its span shown, is excluded from the accepted list, and is never
silently dropped. A game whose capture did not finish is FAILED. Only
OK games are handed forward for pricing; an evening card built from a
manifest with refused games prices the accepted games only and never
falls back silently to an earlier capture for the refused ones.

Input is the dedicated span-record list the capture writes for this
purpose (one record per game), NOT a raw capture game section:

    {"event_id": ..., "capture_started_at": iso-with-tz,
     "capture_finished_at": iso-with-tz or None,
     "failure_reason": optional, only when the capture failed}

Malformed records (missing event id, naive or unparseable timestamps,
finish before start, duplicate event ids, a failure reason on a
finished capture, unknown fields, an empty manifest) raise
CaptureSpanManifestError — fail-closed, never partially evaluated.

Inventory-only until the capture jobs adopt it: nothing imports this
module in production yet, and it changes no pricing, ledger, evaluator,
or capture behavior on its own. Research only; no play authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

VERSION = "DK_CAPTURE_SPAN_MANIFEST_V1"
SPAN_LIMIT_S = 150.0
QUOTE_MAX_AGE_S = 180.0
RECORD_FIELDS = frozenset({
    "event_id", "capture_started_at", "capture_finished_at",
    "failure_reason",
})
STATUS_OK = "OK"
STATUS_REFUSED_SPAN = "REFUSED_SPAN"
STATUS_FAILED = "FAILED"


class CaptureSpanManifestError(ValueError):
    """Safe non-sensitive validation refusal."""


def _time(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise CaptureSpanManifestError("CAPTURE_TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureSpanManifestError("INVALID_CAPTURE_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CaptureSpanManifestError("TIMESTAMP_UTC_OFFSET_REQUIRED")
    return dt


def _event_id(raw: Any) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise CaptureSpanManifestError("EVENT_ID_REQUIRED")
    event_id = str(raw).strip()
    if not event_id:
        raise CaptureSpanManifestError("EVENT_ID_REQUIRED")
    return event_id


def build_capture_span_manifest(records: Any) -> dict[str, Any]:
    """Rule on one capture's per-game span records.

    Returns the manifest: every game listed with its span and status,
    the accepted (OK) event ids, and the refused games with their spans.
    Raises CaptureSpanManifestError on any malformed input.
    """
    if not isinstance(records, list) or not records:
        raise CaptureSpanManifestError("NONEMPTY_SPAN_RECORDS_REQUIRED")
    games = []
    seen = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) - RECORD_FIELDS:
            raise CaptureSpanManifestError("UNEXPECTED_SPAN_RECORD_FIELDS")
        event_id = _event_id(record.get("event_id"))
        if event_id in seen:
            raise CaptureSpanManifestError("DUPLICATE_EVENT_ID")
        seen.add(event_id)
        started_raw = record.get("capture_started_at")
        started = _time(started_raw)
        finished_raw = record.get("capture_finished_at")
        failure_reason = record.get("failure_reason")
        if failure_reason is not None and (
                not isinstance(failure_reason, str) or not failure_reason.strip()):
            raise CaptureSpanManifestError("FAILURE_REASON_INVALID")
        entry: dict[str, Any] = {
            "event_id": event_id,
            "capture_started_at": started_raw,
            "capture_finished_at": finished_raw,
            "span_seconds": None,
        }
        if finished_raw is None:
            entry["status"] = STATUS_FAILED
            if failure_reason is not None:
                entry["failure_reason"] = failure_reason
        else:
            if failure_reason is not None:
                raise CaptureSpanManifestError(
                    "FAILURE_REASON_ON_FINISHED_CAPTURE")
            finished = _time(finished_raw)
            span = (finished - started).total_seconds()
            if span < 0:
                raise CaptureSpanManifestError("CAPTURE_SPAN_CHRONOLOGY_INVALID")
            entry["span_seconds"] = span
            entry["status"] = (
                STATUS_OK if span <= SPAN_LIMIT_S else STATUS_REFUSED_SPAN)
        games.append(entry)
    games.sort(key=lambda g: g["event_id"])
    accepted = [g["event_id"] for g in games if g["status"] == STATUS_OK]
    refused = [{
        "event_id": g["event_id"],
        "status": g["status"],
        "span_seconds": g["span_seconds"],
    } for g in games if g["status"] != STATUS_OK]
    return {
        "version": VERSION,
        "span_limit_seconds": SPAN_LIMIT_S,
        "quote_max_age_seconds": QUOTE_MAX_AGE_S,
        "games": games,
        "accepted_event_ids": accepted,
        "refused": refused,
        "counts": {
            "games": len(games),
            "ok": len(accepted),
            "refused_span": sum(
                1 for g in games if g["status"] == STATUS_REFUSED_SPAN),
            "failed": sum(
                1 for g in games if g["status"] == STATUS_FAILED),
        },
        "status": ("ALL_GAMES_WITHIN_LIMIT" if not refused
                   else "GAMES_REFUSED"),
        "research_only": True,
        "play_authority": False,
    }
