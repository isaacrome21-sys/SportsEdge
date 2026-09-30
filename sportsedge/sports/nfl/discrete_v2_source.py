"""Pinned 2021-2024 REG score bytes for the discrete v2 fit."""
from __future__ import annotations

from base64 import b64decode
from gzip import decompress
from hashlib import sha256
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "nfl_discrete_v2" / "scores_2021_2024_reg.json"
SNAPSHOT_B64 = Path(__file__).resolve().parents[3] / "data" / "nfl_discrete_v2" / "scores_2021_2024_reg.json.gz.b64"
EXPECTED_SOURCE_SHA256 = "90a2ed9d0e77e06ede6d9c9d1c7dc8c36b210c327062a48eb2dd2d6e14629477"


def snapshot_bytes(path: Path | None = None) -> bytes:
    target = path or SNAPSHOT
    if target.exists():
        raw = target.read_bytes()
    else:
        raw = decompress(b64decode(SNAPSHOT_B64.read_text().strip()))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    if digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"NFL_DISCRETE_V2_SOURCE_SHA_MISMATCH:{digest}")
    return raw


def snapshot_sha256(path: Path | None = None) -> str:
    return sha256(snapshot_bytes(path)).hexdigest()
