"""Point-in-time availability gate for computed NFL prop trends.

Kickoff time proves only that a game started before a requested cutoff. It does
not prove that the final player-stat row used by a historical replay was
actually observable at that cutoff. This module keeps those concepts separate.

Computed prop trends remain research/context only. Even a fully attested PIT
availability envelope cannot create Model_P, satisfy Truth Gate, or become
promotion evidence without a separately governed methodology and evidence path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .computed_prop_trends import (
    ComputedPropTrendError,
    ComputedPropTrendSnapshot,
    build_computed_prop_trends,
)


PIT_AVAILABILITY_CONTRACT = "NFL_COMPUTED_PROP_TRENDS_PIT_AVAILABILITY_V1"


@dataclass(frozen=True)
class StatsAvailabilityProof:
    """Proof that one finalized game-stat observation existed by a cutoff."""

    game_id: str
    observed_at: datetime
    source_uri: str
    source_sha256: str
    archive_id: str


@dataclass(frozen=True)
class PitTrendEnvelope:
    contract: str
    snapshot: ComputedPropTrendSnapshot
    cutoff: datetime
    proofs: tuple[StatsAvailabilityProof, ...]
    pit_provenance_complete: bool
    reasons: tuple[str, ...]
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)
    promotion_evidence_eligible: bool = field(default=False, init=False)
    decision_effect: str = field(default="NONE", init=False)


def _utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        try:
            out = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ComputedPropTrendError(f"INVALID_TIMESTAMP:{field_name}") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ComputedPropTrendError(f"TIMEZONE_REQUIRED:{field_name}")
    return out.astimezone(timezone.utc)


def _required_text(value: Any, field_name: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ComputedPropTrendError(f"MISSING_AVAILABILITY_PROOF_FIELD:{field_name}")
    return out


def _sha256(value: Any, field_name: str) -> str:
    out = _required_text(value, field_name).lower()
    if len(out) != 64:
        raise ComputedPropTrendError(f"INVALID_SHA256:{field_name}")
    try:
        int(out, 16)
    except ValueError as exc:
        raise ComputedPropTrendError(f"INVALID_SHA256:{field_name}") from exc
    return out


def _normalize_proof(proof: StatsAvailabilityProof) -> StatsAvailabilityProof:
    game_id = _required_text(proof.game_id, "game_id")
    observed_at = _utc(proof.observed_at, f"observed_at:{game_id}")
    source_uri = _required_text(proof.source_uri, f"source_uri:{game_id}")
    if not source_uri.startswith("https://"):
        raise ComputedPropTrendError(f"HTTPS_SOURCE_REQUIRED:source_uri:{game_id}")
    source_sha256 = _sha256(proof.source_sha256, f"source_sha256:{game_id}")
    archive_id = _required_text(proof.archive_id, f"archive_id:{game_id}")
    return StatsAvailabilityProof(
        game_id=game_id,
        observed_at=observed_at,
        source_uri=source_uri,
        source_sha256=source_sha256,
        archive_id=archive_id,
    )


def attest_stat_availability(
    snapshot: ComputedPropTrendSnapshot,
    *,
    availability_proofs: Iterable[StatsAvailabilityProof],
    as_of: Any | None = None,
) -> PitTrendEnvelope:
    """Audit whether every used game stat was observable at the requested cutoff.

    Missing proof is not silently inferred from kickoff, week number, current
    source contents, or the fact that the game eventually became final.
    """

    cutoff = _utc(snapshot.as_of if as_of is None else as_of, "as_of")
    if cutoff != snapshot.as_of.astimezone(timezone.utc):
        raise ComputedPropTrendError("PIT_CUTOFF_SNAPSHOT_MISMATCH")

    proof_by_game: dict[str, StatsAvailabilityProof] = {}
    for raw in availability_proofs:
        proof = _normalize_proof(raw)
        if proof.game_id in proof_by_game:
            raise ComputedPropTrendError(f"DUPLICATE_STATS_AVAILABILITY_PROOF:{proof.game_id}")
        proof_by_game[proof.game_id] = proof

    reasons: list[str] = []
    used: list[StatsAvailabilityProof] = []
    for game in snapshot.games:
        proof = proof_by_game.get(game.game_id)
        if proof is None:
            reasons.append(f"STAT_AVAILABILITY_UNPROVEN:{game.game_id}")
            continue
        used.append(proof)
        if proof.observed_at > cutoff:
            reasons.append(f"STAT_NOT_AVAILABLE_AT_CUTOFF:{game.game_id}")

    return PitTrendEnvelope(
        contract=PIT_AVAILABILITY_CONTRACT,
        snapshot=snapshot,
        cutoff=cutoff,
        proofs=tuple(sorted(used, key=lambda item: item.game_id)),
        pit_provenance_complete=not reasons,
        reasons=tuple(reasons),
    )


def require_complete_pit_provenance(envelope: PitTrendEnvelope) -> None:
    """Fail closed for any historical/evidence path that requires PIT proof."""

    if not envelope.pit_provenance_complete:
        detail = "|".join(envelope.reasons) or "UNKNOWN"
        raise ComputedPropTrendError(f"PIT_STATS_AVAILABILITY_INCOMPLETE:{detail}")


def build_pit_governed_computed_prop_trends(
    *,
    availability_proofs: Iterable[StatsAvailabilityProof],
    **trend_kwargs: Any,
) -> PitTrendEnvelope:
    """Build the existing context snapshot, then independently attest availability.

    The base trend builder may use kickoff for event ordering. This wrapper is
    the required entry point for historical replay/evidence code because it adds
    the separate observation-availability check that kickoff alone cannot prove.
    """

    snapshot = build_computed_prop_trends(**trend_kwargs)
    return attest_stat_availability(
        snapshot,
        availability_proofs=availability_proofs,
        as_of=trend_kwargs.get("as_of"),
    )
