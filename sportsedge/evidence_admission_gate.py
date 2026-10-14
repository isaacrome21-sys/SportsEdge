"""Shared consumer gate for dual-TSA anchored evidence admission (t127).

Every evidence consumer (Form 2 pinned loader, QB evidence archive, MLB receipt
journal) calls :func:`anchored_admission` instead of talking to the anchor
module directly, so there is exactly ONE admission path.

While ``evidence_anchor.ADMISSION_ACTIVE`` is False (the committed config) this
refuses every anchor with ``admission_not_activated`` before reading anything.
When admission is separately activated by the owner, the bundle must (a) cover
the consumer's bound digest as one of its Merkle leaves and (b) pass
``evidence_anchor.admit_configured_quorum`` (two distinct pinned TSAs, nonce
bound requests, every quorum genTime <= cutoff - margin). Never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from . import evidence_anchor as ea

ANCHOR_SOURCE = ea.ANCHOR_ID
ADMISSION_NOT_ACTIVATED = "admission_not_activated"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GateDecision:
    admitted: bool
    reason: str
    gen_time: datetime | None = None


def _admit(bundle: Mapping, *, event_cutoff: datetime) -> ea.AdmissionDecision:
    """Production admission seam: configured, pinned trust only."""
    return ea.admit_configured_quorum(bundle, event_cutoff=event_cutoff)


def anchored_admission(bundle: Mapping | None, *, bound_sha256: str,
                       event_cutoff: datetime | None) -> GateDecision:
    if not ea.ADMISSION_ACTIVE:
        return GateDecision(False, ADMISSION_NOT_ACTIVATED)
    try:
        if not isinstance(bound_sha256, str) or not _HEX64.match(bound_sha256):
            return GateDecision(False, "bound_digest_invalid")
        if not isinstance(bundle, Mapping):
            return GateDecision(False, "malformed_bundle")
        if not isinstance(event_cutoff, datetime) or event_cutoff.tzinfo is None:
            return GateDecision(False, "cutoff_not_tz_aware")
        leaves = bundle.get("leaves")
        if not isinstance(leaves, (list, tuple)) or bound_sha256 not in leaves:
            return GateDecision(False, "anchor_does_not_cover_digest")
        d = _admit(bundle, event_cutoff=event_cutoff)
        return GateDecision(bool(d.admitted), d.reason, d.gen_time if d.admitted else None)
    except Exception as e:  # fail closed
        return GateDecision(False, f"internal_error:{type(e).__name__}")
