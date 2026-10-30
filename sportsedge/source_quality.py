"""Conservative point-in-time provenance checks for research input evidence.

This module does not authorize model promotion or retroactive use of data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ALLOWED_STATUS = frozenset({"confirmed", "projected", "unknown"})
ALLOWED_LICENSE = frozenset({"permitted", "research_only", "unknown", "restricted"})


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def assess_evidence(record: dict[str, Any], decision_at: str, *, require_confirmed: bool = False,
                    commercial_use: bool = False) -> tuple[str, ...]:
    """Return blocking reason codes; empty tuple means metadata passes checks.

    Passing these checks is NOT independent validation of the source contents.
    """
    reasons: list[str] = []
    for field in ("source", "game_id", "captured_at", "status", "license"):
        if not record.get(field):
            reasons.append(f"MISSING_{field.upper()}")
    capture = _timestamp(record.get("captured_at"))
    decision = _timestamp(decision_at)
    if record.get("captured_at") and capture is None:
        reasons.append("INVALID_CAPTURE_TIME")
    if decision is None:
        reasons.append("INVALID_DECISION_TIME")
    if capture is not None and decision is not None and capture > decision:
        reasons.append("POST_DECISION_EVIDENCE")
    status = record.get("status")
    if status and status not in ALLOWED_STATUS:
        reasons.append("INVALID_STATUS")
    if require_confirmed and status != "confirmed":
        reasons.append("NOT_CONFIRMED")
    license_status = record.get("license")
    if license_status and license_status not in ALLOWED_LICENSE:
        reasons.append("INVALID_LICENSE")
    if commercial_use and license_status != "permitted":
        reasons.append("COMMERCIAL_LICENSE_NOT_VERIFIED")
    return tuple(dict.fromkeys(reasons))
