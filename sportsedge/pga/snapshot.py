from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class SnapshotEnvelope:
    event: str
    round_number: int
    captured_at: str
    payload: Mapping[str, Any]
    sha256: str


def canonical_json(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("PGA_SNAPSHOT_PAYLOAD_MUST_BE_MAPPING")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def make_snapshot_envelope(
    *,
    event: str,
    round_number: int,
    captured_at: datetime,
    payload: Mapping[str, Any],
) -> SnapshotEnvelope:
    if not str(event).strip():
        raise ValueError("PGA_SNAPSHOT_EVENT_REQUIRED")
    if type(round_number) is not int or not 1 <= round_number <= 4:
        raise ValueError("PGA_SNAPSHOT_ROUND_INVALID")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("PGA_SNAPSHOT_TIMESTAMP_TIMEZONE_REQUIRED")
    body = dict(payload)
    return SnapshotEnvelope(
        event=str(event).strip(),
        round_number=round_number,
        captured_at=captured_at.astimezone(timezone.utc).isoformat(),
        payload=body,
        sha256=payload_sha256(body),
    )


def write_snapshot(path: str | Path, envelope: SnapshotEnvelope) -> Path:
    """Write once: point-in-time evidence is immutable, never overwritten."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"snapshot already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(envelope), sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def read_snapshot(path: str | Path) -> SnapshotEnvelope:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    envelope = SnapshotEnvelope(
        event=str(raw["event"]),
        round_number=int(raw["round_number"]),
        captured_at=str(raw["captured_at"]),
        payload=dict(raw["payload"]),
        sha256=str(raw["sha256"]),
    )
    if payload_sha256(envelope.payload) != envelope.sha256:
        raise ValueError("PGA_SNAPSHOT_HASH_MISMATCH")
    try:
        stamp = datetime.fromisoformat(envelope.captured_at)
    except ValueError as exc:
        raise ValueError("PGA_SNAPSHOT_TIMESTAMP_INVALID") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("PGA_SNAPSHOT_TIMESTAMP_TIMEZONE_REQUIRED")
    if not str(envelope.event).strip() or not 1 <= envelope.round_number <= 4:
        raise ValueError("PGA_SNAPSHOT_ENVELOPE_INVALID")
    return envelope
