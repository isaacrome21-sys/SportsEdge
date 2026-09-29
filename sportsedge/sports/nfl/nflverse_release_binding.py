from __future__ import annotations

"""Immutable raw-source binding for nflverse archive assets."""

from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any, Mapping

from .context_autopull import NFLContextError

_ARCHIVE_TAG = re.compile(r"^archive-(\d{4}-\d{2}-\d{2})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BASE = "https://github.com/nflverse/nflverse-data-archives/releases/download"


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def bind_nflverse_archive_asset(
    *,
    kickoff: Any,
    release_tag: str,
    asset_name: str,
    asset_id: int,
    published_at: Any,
    source_uri: str,
    expected_sha256: str,
    raw_bytes: bytes,
    expected_size: int | None = None,
) -> Mapping[str, Any]:
    """Validate and describe one immutable nflverse archive asset."""
    kick = _utc(kickoff, "kickoff")
    published = _utc(published_at, "published_at")
    if published >= kick:
        raise NFLContextError("archive asset must be published before kickoff")

    tag = str(release_tag).strip()
    if not _ARCHIVE_TAG.fullmatch(tag):
        raise NFLContextError("release_tag must be an immutable archive-YYYY-MM-DD tag")
    name = str(asset_name).strip()
    if not name or "/" in name or "\\" in name:
        raise NFLContextError("invalid archive asset_name")
    try:
        aid = int(asset_id)
    except (TypeError, ValueError) as exc:
        raise NFLContextError("invalid archive asset_id") from exc
    if aid <= 0:
        raise NFLContextError("invalid archive asset_id")

    uri = str(source_uri).strip()
    expected_uri = f"{_BASE}/{tag}/{name}"
    if uri != expected_uri:
        raise NFLContextError("archive asset source_uri does not match release tag/name")

    digest = str(expected_sha256).lower().removeprefix("sha256:")
    if not _SHA256.fullmatch(digest):
        raise NFLContextError("invalid expected_sha256")
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise NFLContextError("raw_bytes must be bytes")
    actual = sha256(bytes(raw_bytes)).hexdigest()
    if actual != digest:
        raise NFLContextError("archive asset SHA-256 mismatch")

    size = len(raw_bytes)
    if expected_size is not None:
        try:
            release_size = int(expected_size)
        except (TypeError, ValueError) as exc:
            raise NFLContextError("invalid expected_size") from exc
        if release_size != size:
            raise NFLContextError("archive asset size mismatch")

    return {
        "status": "BOUND",
        "provider": "nflverse-data-archives",
        "release_tag": tag,
        "asset_name": name,
        "asset_id": aid,
        "published_at": published.isoformat(),
        "source_uri": uri,
        "raw_sha256": actual,
        "raw_size": size,
        "kickoff": kick.isoformat(),
        "authority": "RESEARCH_ONLY",
    }
