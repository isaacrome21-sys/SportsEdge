"""Append-only per-attempt capture stage receipts for P0 issue #2792.

This module records *observed* UTC events; it never infers source quote time
from issue updated_at or GitHub job timestamps. No betting authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import uuid

STAGES = ("scheduled_due", "dispatch", "source_capture", "ingestion", "durable_write", "card_delivery", "failure")
TERMINAL = {"card_delivery", "failure"}


def utc_stamp(at: datetime | None = None) -> str:
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("timezone-aware event timestamp required")
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class AttemptLedger:
    """Unique append-only JSONL per game/attempt, with fsync per stage.

    No mutation of prior receipts. A failed stage is explicitly terminal.
    A successful delivery cannot occur without source and durable-write proof.
    """

    def __init__(self, directory: str | Path, *, game_id: str, capture_kind: str,
                 due_utc: str, attempt_id: str | None = None):
        if not game_id or not capture_kind or not due_utc.endswith("Z"):
            raise ValueError("game, capture kind and UTC due time required")
        self.attempt_id = attempt_id or uuid.uuid4().hex
        if not self.attempt_id.isalnum():
            raise ValueError("invalid attempt id")
        self.game_id, self.capture_kind = game_id, capture_kind
        self.path = Path(directory) / (self.attempt_id + ".jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._terminal = False
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._fd = fd
        self.record("scheduled_due", at=datetime.fromisoformat(due_utc.replace("Z", "+00:00")))

    def record(self, stage: str, *, at: datetime | None = None,
               source_timestamp_utc: str | None = None, raw: bytes | None = None,
               receipt_locator: str | None = None, detail: str | None = None) -> dict:
        if stage not in STAGES or self._terminal or stage in self._seen:
            raise ValueError("invalid, duplicate, or post-terminal stage")
        if stage == "source_capture" and (raw is None or not source_timestamp_utc):
            raise ValueError("authenticated source bytes and quote timestamp required")
        if stage == "durable_write" and (not receipt_locator or "source_capture" not in self._seen):
            raise ValueError("durable receipt locator and source capture required")
        if stage == "card_delivery" and "durable_write" not in self._seen:
            raise ValueError("cannot claim delivery before durable write")
        if stage == "failure" and not detail:
            raise ValueError("failure reason required")
        event = {
            "attempt_id": self.attempt_id, "game_id": self.game_id,
            "capture_kind": self.capture_kind, "stage": stage,
            "observed_at_utc": utc_stamp(at),
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
            self.record("failure", detail=f"UNHANDLED:{exc_type.__name__}" if exc_type else "ATTEMPT_ENDED_WITHOUT_DELIVERY")
        os.close(self._fd)
        return False
