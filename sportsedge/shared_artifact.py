"""Fail-closed dependency binding for a shared fitted-model artifact.

This module freezes *identity*, not evidence.  It never creates Model_P, promotes
markets, or claims forward observations.  Raw artifact bytes are the freeze unit;
per-market attestations are valid only for the exact SHA-256 they name.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping, Sequence


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SharedArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class SharedArtifactFreeze:
    artifact_sha256: str
    artifact_version: str


@dataclass(frozen=True)
class MarketArtifactReadiness:
    market: str
    status: str
    ready_for_forward_capture: bool
    current_artifact_sha256: str
    attested_artifact_sha256: str | None
    local_blockers: tuple[str, ...]


def _require_sha256(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise SharedArtifactError(f"{field} must be a lowercase SHA-256")
    return text


def freeze_shared_artifact(artifact_bytes: bytes, *, artifact_version: str) -> SharedArtifactFreeze:
    """Return the immutable identity of real artifact bytes supplied by the caller."""
    if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
        raise SharedArtifactError("artifact_bytes must be non-empty bytes")
    version = str(artifact_version or "").strip()
    if not version:
        raise SharedArtifactError("artifact_version must be non-empty")
    return SharedArtifactFreeze(
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_version=version,
    )


def assess_market_artifact_attestation(
    *,
    market: str,
    current_artifact_sha256: str,
    attestation: Mapping[str, Any],
) -> MarketArtifactReadiness:
    """Evaluate one market's dependency on the currently frozen shared artifact.

    A shared artifact change automatically makes an old market attestation stale.
    Markets clear their own local blockers independently and must explicitly
    declare forward capture against the current hash before becoming capture-ready.
    Capture readiness is deliberately not deployment eligibility or promotion.
    """
    market_name = str(market or "").strip()
    if not market_name:
        raise SharedArtifactError("market must be non-empty")
    if not isinstance(attestation, Mapping):
        raise SharedArtifactError("attestation must be an object")

    current_sha = _require_sha256(current_artifact_sha256, field="current_artifact_sha256")
    attested_raw = attestation.get("shared_artifact_sha256")
    attested_sha: str | None
    try:
        attested_sha = _require_sha256(attested_raw, field="shared_artifact_sha256")
    except SharedArtifactError:
        attested_sha = None

    blockers_raw = attestation.get("local_blockers", ())
    if isinstance(blockers_raw, (str, bytes)) or not isinstance(blockers_raw, Sequence):
        raise SharedArtifactError("local_blockers must be a sequence of blocker codes")
    blockers = tuple(str(item).strip() for item in blockers_raw if str(item).strip())

    if attested_sha != current_sha:
        status = "STALE_SHARED_ARTIFACT"
        ready = False
    elif blockers:
        status = "BLOCKED_LOCAL"
        ready = False
    elif attestation.get("forward_capture_declared") is not True:
        status = "FORWARD_CAPTURE_NOT_DECLARED"
        ready = False
    else:
        status = "READY_FOR_FORWARD_CAPTURE"
        ready = True

    return MarketArtifactReadiness(
        market=market_name,
        status=status,
        ready_for_forward_capture=ready,
        current_artifact_sha256=current_sha,
        attested_artifact_sha256=attested_sha,
        local_blockers=blockers,
    )
