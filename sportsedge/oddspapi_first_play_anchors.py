"""Actual first-play anchors for Check D: provenance-carrying INPUTS.

An anchor records when a game actually started (first play / first
pitch), from a named independent source. Anchors are inputs to the
admission evidence packet. They are NEVER derived from any odds payload:
nothing in this module reads, imports, or infers from provider or
bookmaker data, because a start time extracted from the source under
test would certify itself.

A missing anchor is an explicit state, never an inference: lookups for
an unknown event return {"event_id": ..., "anchor_state": "NO_ANCHOR"},
and no scheduled start, listed start, or neighboring game's time may be
substituted. The provenance SHA-256 attached for the #2446 instrument
is a content hash of the anchor record as supplied; like the instrument
itself states, a hash of claimed provenance is not authentication of
the source. Authentication of anchor sources is the admission run's
separate job.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

VERSION = "ODDSPAPI_FIRST_PLAY_ANCHORS_V1"
RECORD_KEYS = {"event_id", "actual_first_play_at", "source_name",
               "source_url_or_id", "retrieved_at"}
_ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")


class AnchorRefusal(ValueError):
    """Stable refusal code; never include source text beyond the record."""


def _stamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnchorRefusal(name + "_UTC_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnchorRefusal(name + "_UTC_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnchorRefusal(name + "_UTC_OFFSET_REQUIRED")
    return value


def _validate_record(record: Any) -> dict:
    if not isinstance(record, Mapping) or set(record) != RECORD_KEYS:
        raise AnchorRefusal("ANCHOR_RECORD_SCHEMA_INVALID")
    event_id = record.get("event_id")
    if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
        raise AnchorRefusal("ANCHOR_EVENT_ID_INVALID")
    _stamp(record.get("actual_first_play_at"), "ANCHOR_FIRST_PLAY")
    _stamp(record.get("retrieved_at"), "ANCHOR_RETRIEVED_AT")
    for key in ("source_name", "source_url_or_id"):
        if not isinstance(record.get(key), str) or not record.get(key):
            raise AnchorRefusal("ANCHOR_SOURCE_FIELD_MISSING:" + key)
    return dict(record)


def load_anchor_book(records: Sequence[Mapping[str, Any]]) -> dict:
    """Validate anchor records into an event_id -> record book.
    Identical duplicates dedupe; conflicting duplicates refuse."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise AnchorRefusal("ANCHOR_BOOK_INPUT_INVALID")
    book: dict[str, dict] = {}
    for record in records:
        valid = _validate_record(record)
        existing = book.get(valid["event_id"])
        if existing is not None and existing != valid:
            raise AnchorRefusal(
                "ANCHOR_DUPLICATE_CONFLICT:" + valid["event_id"])
        book[valid["event_id"]] = valid
    return book


def get_anchor(book: Mapping[str, Mapping[str, Any]], event_id: str) -> dict:
    """Return the anchor record, or the explicit NO_ANCHOR state.
    Never an inferred, scheduled, or borrowed time."""
    record = book.get(event_id)
    if record is None:
        return {"event_id": event_id, "anchor_state": "NO_ANCHOR"}
    return dict(record)


def anchor_provenance_sha256(record: Mapping[str, Any]) -> str:
    """Content hash of the anchor record exactly as supplied. This binds
    a close candidate to this provenance claim; it does not authenticate
    the source (see module docstring)."""
    valid = _validate_record(record)
    canonical = json.dumps(valid, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return sha256(canonical).hexdigest()


def to_instrument_anchor(record: Mapping[str, Any]) -> dict:
    """Convert a validated anchor record to the actual_first_play shape
    the #2446 numeric instrument consumes:
    {canonical_event_id, actual_first_play_utc, official_source_sha256}.
    A NO_ANCHOR state dict is refused here, not converted: the caller
    must carry the absence explicitly (build_close_candidate does)."""
    if not isinstance(record, Mapping) \
            or record.get("anchor_state") == "NO_ANCHOR":
        raise AnchorRefusal("ANCHOR_ABSENT_CANNOT_CONVERT")
    valid = _validate_record(record)
    return {
        "canonical_event_id": valid["event_id"],
        "actual_first_play_utc": valid["actual_first_play_at"],
        "official_source_sha256": anchor_provenance_sha256(valid),
    }
