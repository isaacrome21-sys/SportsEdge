"""Append-only replay evidence for LIVE_ENGINE_V1.

The archive stores normalized decision inputs/outputs, not mutable latest-state
records. Each record is independently hashable for replay and audit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


LIVE_ARCHIVE_SCHEMA = "SPORTSEDGE_LIVE_ARCHIVE_V1"


@dataclass(frozen=True)
class LiveArchiveRecord:
    event_id: str
    sport: str
    snapshot_id: str
    pit_cutoff: datetime
    recorded_at: datetime
    record_type: str  # STATE / QUOTE / MODEL / DECISION / SETTLEMENT
    payload: Mapping[str, Any]
    schema: str = LIVE_ARCHIVE_SCHEMA

    def validate(self) -> None:
        if self.schema != LIVE_ARCHIVE_SCHEMA:
            raise ValueError("live archive schema mismatch")
        if not self.event_id or not self.sport or not self.snapshot_id:
            raise ValueError("archive identity fields required")
        if self.record_type not in {"STATE", "QUOTE", "MODEL", "DECISION", "SETTLEMENT"}:
            raise ValueError("invalid live archive record_type")
        if self.pit_cutoff.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("archive timestamps must be timezone-aware")
        if self.recorded_at < self.pit_cutoff:
            raise ValueError("recorded_at cannot precede pit_cutoff")

    @property
    def record_hash(self) -> str:
        self.validate()
        body = _canonical(self)
        return sha256(body.encode("utf-8")).hexdigest()


def _canonical(record: LiveArchiveRecord) -> str:
    data = asdict(record)
    data["pit_cutoff"] = record.pit_cutoff.isoformat()
    data["recorded_at"] = record.recorded_at.isoformat()
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def append_record(path: str | Path, record: LiveArchiveRecord) -> str:
    """Append one immutable JSONL record and return its content hash."""
    record.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = json.loads(_canonical(record))
    row["record_hash"] = record.record_hash
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    return record.record_hash


def verify_archive(path: str | Path) -> tuple[int, tuple[int, ...]]:
    """Return record count and 1-based line numbers failing content-hash verification."""
    failures = []
    count = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            count += 1
            row = json.loads(line)
            expected = row.pop("record_hash", None)
            canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
            actual = sha256(canonical.encode("utf-8")).hexdigest()
            if expected != actual:
                failures.append(line_number)
    return count, tuple(failures)
