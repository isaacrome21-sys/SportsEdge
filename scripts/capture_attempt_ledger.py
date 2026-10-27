"""Append-only P0 #2792 capture receipts; no betting/promotion authority.

Stage timestamps are observed UTC times, except the declared scheduled due
target. This receipt structure alone cannot authenticate a DK quote or prove
real browser delivery, which requires separate prospective source evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import uuid

STAGES = ("scheduled_due", "dispatch", "source_capture", "ingestion",
          "durable_write", "card_delivery", "failure")
SUCCESS_STAGES = STAGES[:-1]
TERMINAL = {"card_delivery", "failure"}


def utc_stamp(at: datetime | None = None) -> str:
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("timezone-aware event timestamp required")
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("authenticated source UTC timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authenticated source UTC timestamp invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("authenticated source timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class AttemptLedger:
    """Exclusive-create, fsynced, append-only receipt per game/attempt.

    Callers must record a new attempt on retry, never overwrite previous
    evidence. An unsuccessful close appends a terminal failure.
    """

    def __init__(
        self, directory: str | Path, *, game_id: str, capture_kind: str,
        due_utc: str, attempt_id: str | None = None,
        window_end_utc: str | None = None,
    ):
        if not game_id or not capture_kind:
            raise ValueError("game and capture kind required")
        due = _parse_utc(due_utc)
        cutoff = _parse_utc(window_end_utc) if window_end_utc is not None else None
        if cutoff is not None and cutoff <= due:
            raise ValueError("capture write cutoff must follow scheduled due")
        self.attempt_id = attempt_id or uuid.uuid4().hex
        if not self.attempt_id.isalnum():
            raise ValueError("invalid attempt id")
        self.game_id, self.capture_kind = game_id, capture_kind
        self.window_end_utc = cutoff
        self.path = Path(directory) / (self.attempt_id + ".jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._terminal = False
        self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.record("scheduled_due", at=due)

    def record(
        self, stage: str, *, at: datetime | None = None,
        source_timestamp_utc: str | None = None, raw: bytes | None = None,
        receipt_locator: str | None = None, detail: str | None = None,
    ) -> dict:
        if stage not in STAGES or self._terminal or stage in self._seen:
            raise ValueError("invalid, duplicate, or post-terminal stage")
        observed = at or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("timezone-aware event timestamp required")
        observed = observed.astimezone(timezone.utc)
        if stage == "source_capture":
            if not isinstance(raw, bytes) or not raw or not source_timestamp_utc:
                raise ValueError("authenticated source bytes and quote timestamp required")
            source_at = _parse_utc(source_timestamp_utc)
            if source_at > observed:
                raise ValueError("authenticated source timestamp after observed receipt")
        if stage == "durable_write" and (not receipt_locator or "source_capture" not in self._seen):
            raise ValueError("durable receipt locator and source capture required")
        if stage == "card_delivery" and "durable_write" not in self._seen:
            raise ValueError("cannot claim delivery before durable write")
        if stage == "card_delivery" and not receipt_locator:
            raise ValueError("card delivery requires authenticated issue locator")
        if stage == "card_delivery" and self.window_end_utc is not None and observed >= self.window_end_utc:
            raise ValueError("LATE_CAPTURE_NO_AUTHENTICATED_CLOSE")
        if stage == "failure" and not detail:
            raise ValueError("failure reason required")
        if stage != "failure" and stage != "scheduled_due":
            previous = SUCCESS_STAGES[SUCCESS_STAGES.index(stage) - 1]
            if previous not in self._seen:
                raise ValueError(f"CAPTURE_STAGE_OUT_OF_ORDER:{stage}:missing={previous}")
        event = {
            "attempt_id": self.attempt_id, "game_id": self.game_id,
            "capture_kind": self.capture_kind, "stage": stage,
            "observed_at_utc": utc_stamp(observed),
            "source_timestamp_utc": source_timestamp_utc,
            "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
            "receipt_locator": receipt_locator, "detail": detail,
        }
        os.write(self._fd, (json.dumps(event, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(self._fd)
        self._seen.add(stage)
        self._terminal = stage in TERMINAL
        return event

    def close(self):
        if not self._terminal:
            self.record("failure", detail="ATTEMPT_ENDED_WITHOUT_DELIVERY")
        os.close(self._fd)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._terminal:
            self.record("failure", detail=f"UNHANDLED:{exc_type.__name__}" if exc_type
                        else "ATTEMPT_ENDED_WITHOUT_DELIVERY")
        os.close(self._fd)
        return False
