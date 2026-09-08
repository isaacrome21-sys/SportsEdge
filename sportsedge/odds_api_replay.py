"""Fail-closed replay of frozen raw The Odds API response bytes.

This module deliberately has no network client, URL builder, cache fallback, or API
key path. Replay consumes only bytes declared by a manifest and verifies each
payload SHA-256 before parsing it. The raw provider bytes may live outside the
public SportsEdge repository (for example in a private evidence repository); the
public repository needs only the manifest contract and hashes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

REPLAY_MANIFEST_SCHEMA = "SPORTSEDGE_ODDS_API_RAW_REPLAY_V1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OddsApiReplayError(RuntimeError):
    """Raised whenever frozen replay identity cannot be proved exactly."""


def _safe_relative_path(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = PurePosixPath(raw)
    if (
        not raw
        or parsed.is_absolute()
        or ".." in parsed.parts
        or parsed.parts in {(), (".",)}
    ):
        raise OddsApiReplayError("ODDS_REPLAY_PATH_INVALID")
    return raw


def _sha256_hex(value: Any, *, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise OddsApiReplayError(error)
    return raw


@dataclass(frozen=True)
class FrozenResponse:
    label: str
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class FrozenOddsApiReplay:
    """Verified raw-response index for replay-only acquisition.

    ``raw_root`` is intentionally supplied separately from ``manifest_path`` so
    callers can keep provider bytes in a private checkout while keeping a hash
    manifest in the public SportsEdge repository.
    """

    raw_root: Path
    manifest_sha256: str
    responses: Mapping[str, FrozenResponse]

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str | Path,
        *,
        raw_root: str | Path,
    ) -> "FrozenOddsApiReplay":
        manifest = Path(manifest_path)
        try:
            raw_manifest = manifest.read_bytes()
            payload = json.loads(raw_manifest.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OddsApiReplayError("ODDS_REPLAY_MANIFEST_UNREADABLE") from exc
        if not isinstance(payload, Mapping):
            raise OddsApiReplayError("ODDS_REPLAY_MANIFEST_MAPPING_REQUIRED")
        if payload.get("schema_version") != REPLAY_MANIFEST_SCHEMA:
            raise OddsApiReplayError("ODDS_REPLAY_MANIFEST_SCHEMA_INVALID")
        rows = payload.get("responses")
        if not isinstance(rows, list) or not rows:
            raise OddsApiReplayError("ODDS_REPLAY_RESPONSES_REQUIRED")

        response_map: dict[str, FrozenResponse] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise OddsApiReplayError(f"ODDS_REPLAY_RESPONSE_INVALID:{index}")
            label = str(row.get("label") or "").strip()
            if not label:
                raise OddsApiReplayError(f"ODDS_REPLAY_LABEL_MISSING:{index}")
            if label in response_map:
                raise OddsApiReplayError(f"ODDS_REPLAY_LABEL_DUPLICATE:{label}")
            relative_path = _safe_relative_path(row.get("path"))
            digest = _sha256_hex(row.get("sha256"), error=f"ODDS_REPLAY_SHA256_INVALID:{label}")
            response_map[label] = FrozenResponse(
                label=label,
                relative_path=relative_path,
                sha256=digest,
            )

        root = Path(raw_root)
        return cls(
            raw_root=root,
            manifest_sha256=sha256(raw_manifest).hexdigest(),
            responses=response_map,
        )

    def read_bytes(self, label: str) -> bytes:
        key = str(label or "").strip()
        response = self.responses.get(key)
        if response is None:
            raise OddsApiReplayError(f"ODDS_REPLAY_CACHE_MISS:{key}")
        path = self.raw_root / response.relative_path
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise OddsApiReplayError(f"ODDS_REPLAY_RAW_BYTES_MISSING:{key}") from exc
        actual = sha256(raw).hexdigest()
        if actual != response.sha256:
            raise OddsApiReplayError(
                f"ODDS_REPLAY_RAW_SHA256_MISMATCH:{key}:expected={response.sha256}:actual={actual}"
            )
        return raw

    def read_json(self, label: str) -> Any:
        """Verify raw bytes first, then parse them as part of the replay path."""
        raw = self.read_bytes(label)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OddsApiReplayError(f"ODDS_REPLAY_RAW_JSON_INVALID:{label}") from exc
