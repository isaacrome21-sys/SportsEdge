"""Offline capture records for official NBA injury-report PDFs (research only).

Builds append-only, hash-chained capture records from bytes a caller already holds.
No network, no scheduler, no storage provisioning, no activation, no backfill.
Receipt time comes from a trusted module clock (tests may monkeypatch ``_trusted_now``)
and is kept separate from the report-header effective time. Every expected slot ends
ON_TIME / LATE / MISSED (or AFTER_TIPOFF per game). No slot is guaranteed.
Permission to use the NBA source for this purpose is UNVERIFIED (NBA terms restrict
gambling-related use); nothing here is authorized to run.
"""
from __future__ import annotations

import hashlib
import json
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .injury_report_parser import InjuryReportError, parse_report

SCHEMA = "NBA_INJURY_REPORT_CAPTURE_V1"
ON_TIME_WITHIN = timedelta(minutes=45)
TIME_AGREEMENT = timedelta(minutes=5)
GENESIS = "0" * 64
PERMISSION = "UNVERIFIED_NBA_TERMS_RESTRICT_GAMBLING_USE"
_DT = datetime


class CaptureError(ValueError):
    pass


def _trusted_now() -> datetime:
    return _DT.fromtimestamp(_time.time_ns() / 1e9, tz=timezone.utc)


def _aware(v: Any, label: str) -> datetime:
    if isinstance(v, str):
        v = _DT.fromisoformat(v.replace("Z", "+00:00"))
    if not isinstance(v, _DT) or v.tzinfo is None or v.utcoffset() is None:
        raise CaptureError(f"{label} must be timezone-aware")
    return v.astimezone(timezone.utc)


def _canon(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def line_hash(prev: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(prev.encode() + _canon(body)).hexdigest()


def slot_status(*, slot_utc: datetime, received_at: datetime, last_tipoff_utc: datetime) -> str:
    if received_at <= slot_utc + ON_TIME_WITHIN:
        return "ON_TIME"
    return "LATE" if received_at < last_tipoff_utc else "AFTER_LAST_TIPOFF"


def capture_record(*, prev_hash: str, slot_utc, url: str, raw: bytes, extracted_text: str,
                   http_status: int, http_last_modified: str | None, extractor: str,
                   last_tipoff_utc, fetch_started_at: datetime) -> dict:
    """One received report. received_at is read here from the trusted clock."""
    received = _trusted_now()
    start = _aware(fetch_started_at, "fetch_started_at")
    if not (start <= received):
        raise CaptureError("RECEIPT_BEFORE_FETCH_START")
    if http_status != 200 or not raw:
        raise CaptureError("NOT_A_RECEIPT_USE_missed_record")
    slot, last_tip = _aware(slot_utc, "slot_utc"), _aware(last_tipoff_utc, "last_tipoff_utc")
    sha = hashlib.sha256(raw).hexdigest()
    flags = []
    try:
        parsed = parse_report(extracted_text, pdf_sha256=sha, received_at=received, extractor=extractor)
        effective = parsed["effective_at_utc"]
        rows = len(parsed["rows"])
    except InjuryReportError as exc:
        effective, rows = None, 0
        flags.append(f"PARSE_FAILED:{exc}")
    if http_last_modified and effective:
        from email.utils import parsedate_to_datetime
        lm = parsedate_to_datetime(http_last_modified).astimezone(timezone.utc)
        if abs(lm - _aware(effective, "effective")) > TIME_AGREEMENT:
            flags.append("TIME_INCONSISTENT")
    body = {"schema": SCHEMA, "kind": "RECEIPT", "slot_utc": slot.isoformat(), "url": url,
            "status": slot_status(slot_utc=slot, received_at=received, last_tipoff_utc=last_tip),
            "fetch_started_at_utc": start.isoformat(), "received_at_utc": received.isoformat(),
            "effective_at_utc": effective, "http_status": http_status,
            "http_last_modified": http_last_modified, "content_length": len(raw), "pdf_sha256": sha,
            "rows": rows, "flags": flags, "usable": not flags, "participation": "UNKNOWN",
            "permission": PERMISSION, "prev_line_sha256": prev_hash}
    return {**body, "line_sha256": line_hash(prev_hash, body)}


def missed_record(*, prev_hash: str, slot_utc, url: str, reason: str) -> dict:
    if reason not in {"NOT_PUBLISHED", "RUNNER_DOWN", "NOT_ATTEMPTED"} and not reason.startswith("HTTP_"):
        raise CaptureError("MISSED_REASON_INVALID")
    body = {"schema": SCHEMA, "kind": "MISSED", "slot_utc": _aware(slot_utc, "slot_utc").isoformat(),
            "url": url, "status": "MISSED", "reason": reason,
            "recorded_at_utc": _trusted_now().isoformat(), "usable": False,
            "permission": PERMISSION, "prev_line_sha256": prev_hash}
    return {**body, "line_sha256": line_hash(prev_hash, body)}


def verify_chain(lines: Iterable[Mapping[str, Any]], *, anchored_head: str) -> bool:
    """Recompute the chain; the head must equal an anchor stored OUTSIDE the log."""
    prev = GENESIS
    for ln in lines:
        body = {k: v for k, v in ln.items() if k != "line_sha256"}
        if body.get("prev_line_sha256") != prev or line_hash(prev, body) != ln.get("line_sha256"):
            return False
        prev = ln["line_sha256"]
    return prev == anchored_head


def usable_as_of(lines: Iterable[Mapping[str, Any]], cutoff) -> dict | None:
    """Latest usable receipt strictly received before cutoff (never effective time)."""
    c = _aware(cutoff, "cutoff")
    ok = [ln for ln in lines if ln.get("kind") == "RECEIPT" and ln.get("usable")
          and _aware(ln["received_at_utc"], "r") < c]
    return max(ok, key=lambda ln: ln["received_at_utc"]) if ok else None
