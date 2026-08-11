"""Canonical fixture transport helpers.

Compressed transport is allowed only as a byte-preserving container. Acceptance
always hashes and consumes the decompressed canonical fixture bytes.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path


class FixtureIOError(ValueError):
    pass


def read_canonical_fixture_bytes(path: str | Path, *, expected_sha256: str) -> bytes:
    p = Path(path)
    transported = p.read_bytes()
    try:
        canonical = gzip.decompress(transported) if transported.startswith(b"\x1f\x8b") else transported
    except (OSError, EOFError) as exc:
        raise FixtureIOError("invalid gzip fixture transport") from exc
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected_sha256:
        raise FixtureIOError(f"fixture hash mismatch: {digest}")
    return canonical
