"""Canonical multi-source provenance manifest for NFL production evidence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        raise ValueError(error)
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError(error) from exc
    return raw


def build_nfl_source_manifest(
    sources: Iterable[Mapping[str, Any]],
    *,
    schedule_anchor_sha256: str,
) -> dict[str, Any]:
    anchor = _sha256(schedule_anchor_sha256, "NFL_SOURCE_SCHEDULE_ANCHOR_INVALID")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in sources:
        name = str(raw.get("name") or "").strip()
        uri = str(raw.get("uri") or "").strip()
        if not name:
            raise ValueError("NFL_SOURCE_NAME_REQUIRED")
        if name in seen:
            raise ValueError(f"NFL_SOURCE_NAME_DUPLICATE:{name}")
        if not uri:
            raise ValueError(f"NFL_SOURCE_URI_REQUIRED:{name}")
        seen.add(name)
        normalized.append({
            "name": name,
            "uri": uri,
            "sha256": _sha256(raw.get("sha256"), f"NFL_SOURCE_SHA256_INVALID:{name}"),
        })
    if not normalized:
        raise ValueError("NFL_SOURCE_MANIFEST_EMPTY")
    schedule = next((row for row in normalized if row["name"] == "schedule"), None)
    if schedule is None:
        raise ValueError("NFL_SOURCE_SCHEDULE_ENTRY_REQUIRED")
    if schedule["sha256"] != anchor:
        raise ValueError("NFL_SOURCE_SCHEDULE_ANCHOR_MISMATCH")
    normalized.sort(key=lambda row: (row["name"], row["uri"], row["sha256"]))
    return {
        "schema_version": 1,
        "sport": "nfl",
        "schedule_anchor_sha256": anchor,
        "sources": normalized,
    }


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
