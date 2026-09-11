"""Strict JSON ingress for manually supplied canonical evidence packets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import EvidenceError, EvidencePacket

EVIDENCE_FILE_SCHEMA = "sportsedge_evidence_v1"
_PACKET_FIELDS = frozenset({
    "game_id",
    "fact_type",
    "subject_id",
    "value",
    "source_name",
    "observed_at_utc",
    "acquisition_mode",
    "authority",
    "verified",
    "scope",
    "market",
    "entity_id",
    "expires_at_utc",
    "gate_action",
    "confidence",
    "metadata",
})
_REQUIRED_FIELDS = frozenset({
    "game_id", "fact_type", "subject_id", "value", "source_name", "observed_at_utc"
})


def evidence_packet_from_mapping(
    raw: Mapping[str, Any],
    *,
    default_acquisition_mode: str = "MANUAL",
) -> EvidencePacket:
    if not isinstance(raw, Mapping):
        raise EvidenceError("evidence packet must be an object")
    unknown = set(raw) - _PACKET_FIELDS
    if unknown:
        raise EvidenceError(f"unknown evidence packet fields:{sorted(unknown)}")
    missing = _REQUIRED_FIELDS - set(raw)
    if missing:
        raise EvidenceError(f"missing evidence packet fields:{sorted(missing)}")
    payload = dict(raw)
    payload.setdefault("acquisition_mode", default_acquisition_mode)
    return EvidencePacket(**payload)


def evidence_packets_from_payload(
    payload: Any,
    *,
    default_acquisition_mode: str = "MANUAL",
) -> tuple[EvidencePacket, ...]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        if payload.get("schema_version") != EVIDENCE_FILE_SCHEMA:
            raise EvidenceError("evidence file schema_version mismatch")
        rows = payload.get("packets")
        if not isinstance(rows, list):
            raise EvidenceError("evidence file packets must be a list")
        unknown = set(payload) - {"schema_version", "packets"}
        if unknown:
            raise EvidenceError(f"unknown evidence file fields:{sorted(unknown)}")
    else:
        raise EvidenceError("evidence file must be a list or schema envelope")
    return tuple(
        evidence_packet_from_mapping(
            row,
            default_acquisition_mode=default_acquisition_mode,
        )
        for row in rows
    )


def load_evidence_file(
    path: str | Path,
    *,
    default_acquisition_mode: str = "MANUAL",
) -> tuple[EvidencePacket, ...]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text())
    except Exception as exc:
        raise EvidenceError(f"evidence file unreadable:{source}") from exc
    return evidence_packets_from_payload(
        payload,
        default_acquisition_mode=default_acquisition_mode,
    )


def evidence_file_payload(packets: Sequence[EvidencePacket]) -> dict[str, Any]:
    """Return a durable envelope while excluding computed packet hashes from ingress."""
    rows = []
    for packet in packets:
        rows.append({
            "game_id": packet.game_id,
            "fact_type": packet.fact_type,
            "subject_id": packet.subject_id,
            "value": packet.value,
            "source_name": packet.source_name,
            "observed_at_utc": packet.observed_at_utc,
            "acquisition_mode": packet.acquisition_mode,
            "authority": packet.authority,
            "verified": packet.verified,
            "scope": packet.scope,
            "market": packet.market,
            "entity_id": packet.entity_id,
            "expires_at_utc": packet.expires_at_utc,
            "gate_action": packet.gate_action,
            "confidence": packet.confidence,
            "metadata": dict(packet.metadata),
        })
    return {"schema_version": EVIDENCE_FILE_SCHEMA, "packets": rows}
