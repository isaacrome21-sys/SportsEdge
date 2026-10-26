"""Content-addressed archival of exact NHL Gamecenter HTTP response bytes.

Receipts contain the source URIs, capture times and SHA-256 digests; this
module stores and verifies the two raw bodies independently. No inferred
historical timestamps or reconstructed JSON are admitted as raw evidence.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame


def _digest(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise TypeError("NHL raw response must be bytes")
    return hashlib.sha256(raw).hexdigest()


def _path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid NHL raw archive SHA-256")
    return root / "sha256" / f"{digest}.json"


def _verify_blob(path: Path, expected_sha: str) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"NHL_RAW_ARCHIVE_MISSING:{expected_sha}") from exc
    if _digest(data) != expected_sha:
        raise ValueError(f"NHL_RAW_ARCHIVE_HASH_MISMATCH:{expected_sha}")


def _store_blob(root: Path, expected_sha: str, raw: bytes) -> None:
    if _digest(raw) != expected_sha:
        raise ValueError(f"NHL_RAW_RESPONSE_HASH_MISMATCH:{expected_sha}")
    dest = _path(root, expected_sha)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _verify_blob(dest, expected_sha)
        return
    fd, tmp = tempfile.mkstemp(prefix=".nhl-raw-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create-if-absent: never overwrite a prior capture or repair
        # a corrupt blob silently. A racing writer is checked below.
        try:
            os.link(tmp, dest)
        except FileExistsError:
            pass
        _verify_blob(dest, expected_sha)
    finally:
        Path(tmp).unlink(missing_ok=True)


def archive_pair(root: Path, receipt: "NHLOfficialCompletedGame", box_raw: bytes, landing_raw: bytes) -> None:
    """Archive both original bodies before a live receipt can be admitted."""
    if receipt.source_version != "nhl-web-api-v1-live2" or not receipt.landing_raw_sha256:
        raise ValueError("NHL_RAW_ARCHIVE_REQUIRES_DUAL_SOURCE_LIVE_RECEIPT")
    # Check both hashes before writing either file.
    if _digest(box_raw) != receipt.source_raw_sha256:
        raise ValueError("NHL_RAW_RESPONSE_HASH_MISMATCH:boxscore")
    if _digest(landing_raw) != receipt.landing_raw_sha256:
        raise ValueError("NHL_RAW_RESPONSE_HASH_MISMATCH:landing")
    _store_blob(root, receipt.source_raw_sha256, box_raw)
    _store_blob(root, receipt.landing_raw_sha256, landing_raw)
    verify_archive(root, receipt)


def verify_archive(root: Path, receipt: "NHLOfficialCompletedGame") -> None:
    """Fail closed on missing/tampered bodies; legacy receipts are not upgraded."""
    if receipt.source_version != "nhl-web-api-v1-live2" or not receipt.landing_raw_sha256:
        raise ValueError("NHL_RAW_ARCHIVE_REQUIRES_DUAL_SOURCE_LIVE_RECEIPT")
    for digest in (receipt.source_raw_sha256, receipt.landing_raw_sha256):
        _verify_blob(_path(root, digest), digest)
