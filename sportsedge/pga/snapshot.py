from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
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
    """Stable JSON encoding used for point-in-time PGA snapshot hashes."""
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
    return SnapshotEnvelope(
        event=event,
        round_number=int(round_number),
        captured_at=captured_at.isoformat(),
        payload=dict(payload),
        sha256=payload_sha256(payload),
    )


def write_snapshot(path: str | Path, envelope: SnapshotEnvelope) -> Path:
    """Write a snapshot without mutating previously captured evidence."""
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
    actual = payload_sha256(envelope.payload)
    if actual != envelope.sha256:
        raise ValueError("snapshot hash mismatch")
    return envelope
