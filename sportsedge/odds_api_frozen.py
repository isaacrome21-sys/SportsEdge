"""Raw-byte freeze/replay support for paid The Odds API responses.

The raw provider bytes are intentionally *not* repository assets in SportsEdge.
A public manifest may describe their hashes and opaque private-repository paths,
but replay reads the bytes from a separately checked-out private fixture root.

Replay has no network fallback. A missing manifest entry, missing private byte
file, path escape, or SHA mismatch raises ``FrozenOddsReplayError``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit

MANIFEST_SCHEMA = "THE_ODDS_API_RAW_FREEZE_MANIFEST_V1"
_PROVIDER_HOST = "api.the-odds-api.com"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_QUERY_KEYS = frozenset({"apikey", "api_key", "key", "token"})


class FrozenOddsReplayError(RuntimeError):
    """Raised when a frozen replay cannot prove/use the exact raw response bytes."""


@dataclass(frozen=True)
class FrozenResponseEntry:
    request_sha256: str
    response_sha256: str
    private_path: str
    byte_length: int


class _BytesResponse:
    """Minimal context-manager response compatible with urllib-style callers."""

    def __init__(self, payload: bytes):
        self._payload = bytes(payload)

    def __enter__(self) -> "_BytesResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _hex64(value: Any, error: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise FrozenOddsReplayError(error)
    return text


def _safe_private_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    parsed = PurePosixPath(raw)
    if not raw or parsed.is_absolute() or ".." in parsed.parts or parsed.parts == (".",):
        raise FrozenOddsReplayError("FROZEN_ODDS_PRIVATE_PATH_INVALID")
    return parsed.as_posix()


def canonical_request_identity(url_or_request: Any) -> bytes:
    """Return a secret-free canonical request identity.

    The provider API key never enters the identity or public manifest. Query
    ordering is normalized because transport ordering is not provider semantics.
    The response bytes themselves are *not* normalized anywhere.
    """
    url = getattr(url_or_request, "full_url", url_or_request)
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    if host != _PROVIDER_HOST:
        raise FrozenOddsReplayError(f"FROZEN_ODDS_PROVIDER_HOST_INVALID:{host}")
    clean_query = [
        (str(key), str(value))
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if str(key).lower() not in _SECRET_QUERY_KEYS
    ]
    clean_query.sort()
    identity = {
        "method": str(getattr(url_or_request, "method", None) or "GET").upper(),
        "host": host,
        "path": parts.path,
        "query": urlencode(clean_query, doseq=True),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_sha256(url_or_request: Any) -> str:
    return hashlib.sha256(canonical_request_identity(url_or_request)).hexdigest()


def raw_response_sha256(raw_bytes: bytes) -> str:
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise TypeError("raw response must be bytes")
    return hashlib.sha256(bytes(raw_bytes)).hexdigest()


def build_public_manifest_entry(
    *,
    url_or_request: Any,
    raw_response_bytes: bytes,
    private_path: str,
) -> dict[str, Any]:
    """Build metadata safe for the public repo; raw bytes are never returned."""
    raw = bytes(raw_response_bytes)
    return {
        "request_sha256": request_sha256(url_or_request),
        "response_sha256": raw_response_sha256(raw),
        "private_path": _safe_private_path(private_path),
        "byte_length": len(raw),
    }


def load_public_manifest(payload: Mapping[str, Any]) -> dict[str, FrozenResponseEntry]:
    if not isinstance(payload, Mapping):
        raise FrozenOddsReplayError("FROZEN_ODDS_MANIFEST_MAPPING_REQUIRED")
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise FrozenOddsReplayError("FROZEN_ODDS_MANIFEST_SCHEMA_INVALID")
    entries = payload.get("responses")
    if not isinstance(entries, list) or not entries:
        raise FrozenOddsReplayError("FROZEN_ODDS_MANIFEST_RESPONSES_REQUIRED")
    out: dict[str, FrozenResponseEntry] = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise FrozenOddsReplayError(f"FROZEN_ODDS_MANIFEST_ENTRY_INVALID:{index}")
        req = _hex64(raw.get("request_sha256"), f"FROZEN_ODDS_REQUEST_SHA_INVALID:{index}")
        resp = _hex64(raw.get("response_sha256"), f"FROZEN_ODDS_RESPONSE_SHA_INVALID:{index}")
        path = _safe_private_path(raw.get("private_path"))
        try:
            length = int(raw.get("byte_length"))
        except (TypeError, ValueError) as exc:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_BYTE_LENGTH_INVALID:{index}") from exc
        if length < 0:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_BYTE_LENGTH_INVALID:{index}")
        entry = FrozenResponseEntry(req, resp, path, length)
        prior = out.get(req)
        if prior is not None and prior != entry:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_REQUEST_DUPLICATE_CONFLICT:{req}")
        out[req] = entry
    return out


class FrozenOddsReplayStore:
    """Strict raw-byte replay transport backed only by private checked-out bytes."""

    def __init__(self, *, private_root: Path | str, manifest: Mapping[str, Any]):
        self._root = Path(private_root).resolve()
        self._entries = load_public_manifest(manifest)

    @classmethod
    def from_manifest_file(
        cls,
        *,
        private_root: Path | str,
        manifest_path: Path | str,
    ) -> "FrozenOddsReplayStore":
        try:
            raw = Path(manifest_path).read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenOddsReplayError("FROZEN_ODDS_MANIFEST_UNREADABLE") from exc
        return cls(private_root=private_root, manifest=payload)

    def _read_entry(self, entry: FrozenResponseEntry) -> bytes:
        path = (self._root / entry.private_path).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise FrozenOddsReplayError("FROZEN_ODDS_PRIVATE_PATH_ESCAPE") from exc
        if not path.is_file():
            raise FrozenOddsReplayError(f"FROZEN_ODDS_CACHE_MISS:{entry.private_path}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_READ_FAILED:{entry.private_path}") from exc
        if len(raw) != entry.byte_length:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_BYTE_LENGTH_MISMATCH:{entry.private_path}")
        digest = raw_response_sha256(raw)
        if digest != entry.response_sha256:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_RESPONSE_SHA_MISMATCH:{entry.private_path}")
        return raw

    def raw_bytes_for(self, url_or_request: Any) -> bytes:
        req = request_sha256(url_or_request)
        entry = self._entries.get(req)
        if entry is None:
            raise FrozenOddsReplayError(f"FROZEN_ODDS_REQUEST_NOT_MANIFESTED:{req}")
        return self._read_entry(entry)

    def open(self, request: Any, timeout: float | None = None) -> _BytesResponse:
        """urllib-compatible opener with no network implementation or fallback."""
        del timeout
        return _BytesResponse(self.raw_bytes_for(request))
