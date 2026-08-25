"""Event-specific UFC promotion policy.

Generic UFC promotion is necessary but not sufficient for DWCS. Contender Series
prospects have a different data regime, so a future generic UFC promotion may not
silently authorize official DWCS bets without separate DWCS evidence.
"""
from __future__ import annotations

from collections.abc import Mapping


def is_dwcs_event(event_name: str | None) -> bool:
    text = " ".join(str(event_name or "").lower().split())
    return "contender series" in text or "dwcs" in text


def _validation_promoted(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and bool(value.get("promoted"))
        and str(value.get("status") or "").upper() == "PROMOTED"
    )


def promotion_for_event(
    evidence: Mapping[str, object], event_name: str | None
) -> dict[str, object]:
    out = dict(evidence)
    blockers = [str(x) for x in (evidence.get("blockers") or [])]

    if is_dwcs_event(event_name) and not _validation_promoted(
        evidence.get("dwcs_specific_validation")
    ):
        if "DWCS_VALIDATION_UNPROMOTED" not in blockers:
            blockers.append("DWCS_VALIDATION_UNPROMOTED")
        out["promoted"] = False
        out["status"] = "UNVERIFIED"

    out["blockers"] = blockers
    out["event_name"] = str(event_name or "")
    out["event_specific_policy"] = "DWCS_SEPARATE_PROMOTION_REQUIRED"
    return out
