from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from sportsedge.mlb_market_snapshot import MLBMarketSnapshot


class SnapshotStoreError(RuntimeError):
    pass


class DuplicateSnapshotError(SnapshotStoreError):
    pass


@dataclass(frozen=True)
class SnapshotArtifact:
    path: str
    content_hash: str
    snapshot_id: str


@dataclass(frozen=True)
class ManifestEntry:
    snapshot_id: str
    content_hash: str
    path: str
    utc_timestamp: str
    git_sha: str
    branch: str
    markets_covered: tuple[str, ...]
    notes: str | None
    created_at: str


def _artifact_bytes(snapshot: MLBMarketSnapshot) -> bytes:
    return (snapshot.to_json() + "\n").encode("utf-8")


def _atomic_write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SnapshotStoreError(f"refusing to overwrite {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "xb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if temp.exists():
            temp.unlink()


def _load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise SnapshotStoreError("manifest must be a JSON list")
    return data


def _write_manifest_atomic(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(entries, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "xb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if temp.exists():
            temp.unlink()


def write_snapshot(snapshot: MLBMarketSnapshot, *, root: str | Path) -> SnapshotArtifact:
    root = Path(root)
    manifest_path = root / "manifest.json"
    existing = _load_manifest(manifest_path)
    if any(e.get("content_hash") == snapshot.content_sha256 for e in existing):
        raise DuplicateSnapshotError(snapshot.content_sha256)

    ts = datetime.fromisoformat(snapshot.snapshot_timestamp.replace("Z", "+00:00"))
    day_dir = root / "snapshots" / f"{ts:%Y}" / f"{ts:%m}" / f"{ts:%d}"
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    final_path = day_dir / f"snapshot-{stamp}-{snapshot.content_sha256[:12]}.json"
    payload = _artifact_bytes(snapshot)
    _atomic_write_new(final_path, payload)

    # Verify exact persisted bytes before indexing the artifact.
    persisted = final_path.read_bytes()
    if persisted != payload:
        raise SnapshotStoreError("persisted snapshot bytes differ from written bytes")

    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry = ManifestEntry(
        snapshot.snapshot_id, snapshot.content_sha256, str(final_path.relative_to(root)),
        snapshot.snapshot_timestamp, snapshot.git_sha, snapshot.branch,
        tuple(str(r["market"]) for r in snapshot.markets), snapshot.notes, created,
    )
    _write_manifest_atomic(manifest_path, existing + [asdict(entry)])
    return SnapshotArtifact(str(final_path), snapshot.content_sha256, snapshot.snapshot_id)


def list_snapshots(*, root: str | Path, market: str | None = None) -> list[ManifestEntry]:
    entries = [ManifestEntry(**e) for e in _load_manifest(Path(root) / "manifest.json")]
    if market is not None:
        entries = [e for e in entries if market in e.markets_covered]
    return sorted(entries, key=lambda e: e.utc_timestamp)


def get_by_hash(content_hash: str, *, root: str | Path) -> ManifestEntry | None:
    return next((e for e in list_snapshots(root=root) if e.content_hash == content_hash), None)


def get_latest(*, root: str | Path, market: str | None = None) -> ManifestEntry | None:
    entries = list_snapshots(root=root, market=market)
    return entries[-1] if entries else None


def read_snapshot_bytes(entry: ManifestEntry, *, root: str | Path) -> bytes:
    return (Path(root) / entry.path).read_bytes()
