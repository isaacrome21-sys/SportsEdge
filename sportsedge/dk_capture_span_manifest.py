"""Per-game DraftKings capture-span manifest (research inventory only).

Owner policy, Oct 25, 2026:
* <=150s captured per game: OK, eligible for a later ladder assessment.
* >150 through 300s: FLAGGED_RESEARCH, retained for PAPER grading only,
  never accepted as ladder evidence.
* >300s: REFUSED_SPAN; failed captures remain FAILED.
* Independent sportsbook quote age is <=1800s. This module only reports
  the quote-age limit; live pricing must enforce that separate wall clock
  against the original Captured timestamp, never GitHub issue edit time.

Every entry preserves original offset-bearing timestamps and span_seconds.
All records remain visible, including refused and failed entries. The two
lists accepted_event_ids (<=150s) and research_event_ids (151-300s) must
never overlap; research_event_ids carry NO ladder/promotion authority.
Malformed/duplicate records fail the entire manifest.

This module is NOT wired into production capture, pricing or settlement:
changing its research manifest alone does not make a quote admissible,
count toward the 50-pick market gate or authorize a PLAY.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

VERSION = "DK_CAPTURE_SPAN_MANIFEST_V2"
SPAN_LIMIT_S = 150.0
RESEARCH_SPAN_LIMIT_S = 300.0
QUOTE_MAX_AGE_S = 1800.0
RECORD_FIELDS = frozenset({
    "event_id", "capture_started_at", "capture_finished_at",
    "failure_reason",
})
STATUS_OK = "OK"
STATUS_FLAGGED_RESEARCH = "FLAGGED_RESEARCH"
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
            "ladder_eligible_by_span": False,
            "paper_research_by_span": False,
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
            if span <= SPAN_LIMIT_S:
                entry["status"] = STATUS_OK
                entry["ladder_eligible_by_span"] = True
            elif span <= RESEARCH_SPAN_LIMIT_S:
                entry["status"] = STATUS_FLAGGED_RESEARCH
                entry["paper_research_by_span"] = True
            else:
                entry["status"] = STATUS_REFUSED_SPAN
        games.append(entry)
    games.sort(key=lambda g: g["event_id"])
    accepted = [g["event_id"] for g in games if g["status"] == STATUS_OK]
    research = [g["event_id"] for g in games
                if g["status"] == STATUS_FLAGGED_RESEARCH]
    flagged = [{"event_id": g["event_id"], "status": g["status"],
                "span_seconds": g["span_seconds"], "ladder_eligible": False}
               for g in games if g["status"] == STATUS_FLAGGED_RESEARCH]
    refused = [{
        "event_id": g["event_id"],
        "status": g["status"],
        "span_seconds": g["span_seconds"],
    } for g in games if g["status"] in {STATUS_REFUSED_SPAN, STATUS_FAILED}]
    return {
        "version": VERSION,
        "span_limit_seconds": SPAN_LIMIT_S,
        "research_span_limit_seconds": RESEARCH_SPAN_LIMIT_S,
        "quote_max_age_seconds": QUOTE_MAX_AGE_S,
        "quote_age_enforced_here": False,
        "games": games,
        "accepted_event_ids": accepted,
        "research_event_ids": research,
        "flagged": flagged,
        "refused": refused,
        "counts": {
            "games": len(games),
            "ok": len(accepted),
            "flagged_research": len(research),
            "refused_span": sum(
                1 for g in games if g["status"] == STATUS_REFUSED_SPAN),
            "failed": sum(
                1 for g in games if g["status"] == STATUS_FAILED),
        },
        "status": ("GAMES_REFUSED" if refused else
                   "GAMES_FLAGGED_RESEARCH" if flagged else
                   "ALL_GAMES_WITHIN_LIMIT"),
        "research_only": True,
        "play_authority": False,
    }
