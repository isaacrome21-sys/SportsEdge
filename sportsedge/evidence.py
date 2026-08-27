"""Canonical evidence packets and fail-closed conflict resolution.

Acquisition mode is provenance only. It is deliberately excluded from evidence
ranking so MANUAL, HYBRID and AUTOMATIC runs make the same decision from the same
facts. Source authority, verification state and event time determine which fact
wins. Simultaneous equally authoritative contradictions fail closed; a strictly
newer official fact may supersede older official state such as a late scratch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
import hashlib
import json

VALID_ACQUISITION_MODES = frozenset({"MANUAL", "HYBRID", "AUTOMATIC"})
VALID_AUTHORITIES = frozenset({"ADVISORY", "PRIMARY", "AUTHORITATIVE"})
VALID_SCOPES = frozenset({"GAME", "MARKET", "ENTITY", "MARKET_ENTITY"})
VALID_GATE_ACTIONS = frozenset({"NONE", "BLOCK_MATCHING"})
AUTHORITY_RANK = {"ADVISORY": 1, "PRIMARY": 2, "AUTHORITATIVE": 3}
SCOPE_RANK = {"ENTITY": 1, "MARKET_ENTITY": 2, "MARKET": 3, "GAME": 4}


class EvidenceError(ValueError):
    pass


def _utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise EvidenceError(f"{field_name} must be ISO-8601") from exc
    else:
        raise EvidenceError(f"{field_name} is required")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise EvidenceError(f"{field_name} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceError("evidence payload is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class EvidencePacket:
    game_id: str
    fact_type: str
    subject_id: str
    value: Any
    source_name: str
    observed_at_utc: str
    acquisition_mode: str
    authority: str = "ADVISORY"
    verified: bool = False
    scope: str = "GAME"
    market: str | None = None
    entity_id: str | None = None
    expires_at_utc: str | None = None
    gate_action: str = "NONE"
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_sha256: str = ""

    def __post_init__(self) -> None:
        game_id = str(self.game_id or "").strip()
        fact_type = str(self.fact_type or "").strip().upper()
        subject_id = str(self.subject_id or "").strip()
        source_name = str(self.source_name or "").strip()
        mode = str(self.acquisition_mode or "").strip().upper()
        authority = str(self.authority or "").strip().upper()
        scope = str(self.scope or "").strip().upper()
        gate_action = str(self.gate_action or "").strip().upper()
        market = _clean_optional(self.market)
        if market is not None:
            market = market.upper()
        entity_id = _clean_optional(self.entity_id)
        if not game_id or not fact_type or not subject_id or not source_name:
            raise EvidenceError("game_id/fact_type/subject_id/source_name are required")
        if mode not in VALID_ACQUISITION_MODES:
            raise EvidenceError(f"unsupported acquisition_mode:{mode}")
        if authority not in VALID_AUTHORITIES:
            raise EvidenceError(f"unsupported authority:{authority}")
        if scope not in VALID_SCOPES:
            raise EvidenceError(f"unsupported scope:{scope}")
        if gate_action not in VALID_GATE_ACTIONS:
            raise EvidenceError(f"unsupported gate_action:{gate_action}")
        if scope in {"MARKET", "MARKET_ENTITY"} and not market:
            raise EvidenceError(f"scope {scope} requires market")
        if scope in {"ENTITY", "MARKET_ENTITY"} and not entity_id:
            raise EvidenceError(f"scope {scope} requires entity_id")
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError) as exc:
            raise EvidenceError("confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise EvidenceError("confidence must be between 0 and 1")
        observed = _utc(self.observed_at_utc, "observed_at_utc")
        expires = None
        if self.expires_at_utc is not None:
            expires = _utc(self.expires_at_utc, "expires_at_utc")
            if expires <= observed:
                raise EvidenceError("expires_at_utc must be after observed_at_utc")
        metadata = dict(self.metadata or {})
        _canonical_json(metadata)
        material = {
            "game_id": game_id,
            "fact_type": fact_type,
            "subject_id": subject_id,
            "value": self.value,
            "source_name": source_name,
            "observed_at_utc": observed.isoformat(),
            # acquisition_mode is provenance, not decision semantics, and is
            # intentionally excluded from this content hash.
            "authority": authority,
            "verified": bool(self.verified),
            "scope": scope,
            "market": market,
            "entity_id": entity_id,
            "expires_at_utc": expires.isoformat() if expires else None,
            "gate_action": gate_action,
            "confidence": confidence,
            "metadata": metadata,
        }
        object.__setattr__(self, "game_id", game_id)
        object.__setattr__(self, "fact_type", fact_type)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "observed_at_utc", observed.isoformat())
        object.__setattr__(self, "acquisition_mode", mode)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "expires_at_utc", expires.isoformat() if expires else None)
        object.__setattr__(self, "gate_action", gate_action)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "content_sha256", _sha256(material))

    @property
    def fact_key(self) -> tuple[str, str, str, str | None, str | None]:
        return (self.game_id, self.fact_type, self.subject_id, self.market, self.entity_id)


@dataclass(frozen=True)
class EvidenceConflict:
    fact_key: tuple[str, str, str, str | None, str | None]
    severity: str
    reason: str
    winner_sha256: str | None
    competing_sha256: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceBlock:
    game_id: str
    scope: str
    market: str | None
    entity_id: str | None
    reason: str
    fact_type: str
    subject_id: str

    def matches(self, *, game_id: str, market: str, entity_id: str) -> bool:
        if str(game_id) != self.game_id:
            return False
        if self.scope == "GAME":
            return True
        if self.scope == "MARKET":
            return str(market).upper() == str(self.market).upper()
        if self.scope == "ENTITY":
            return str(entity_id) == str(self.entity_id)
        return (
            str(market).upper() == str(self.market).upper()
            and str(entity_id) == str(self.entity_id)
        )


@dataclass(frozen=True)
class EvidenceResolution:
    winners: tuple[EvidencePacket, ...]
    conflicts: tuple[EvidenceConflict, ...]
    blocks: tuple[EvidenceBlock, ...]
    rejected_stale: tuple[str, ...]

    @property
    def status(self) -> str:
        return "BLOCKED" if self.blocks else "PASS"

    def block_for(self, *, game_id: str, market: str, entity_id: str) -> EvidenceBlock | None:
        for block in self.blocks:
            if block.matches(game_id=game_id, market=market, entity_id=entity_id):
                return block
        return None


def _priority(packet: EvidencePacket) -> tuple[int, int]:
    return (1 if packet.verified else 0, AUTHORITY_RANK[packet.authority])


def _sort_key(packet: EvidencePacket) -> tuple[int, int, float, float, str]:
    observed = _utc(packet.observed_at_utc, "observed_at_utc").timestamp()
    return (
        1 if packet.verified else 0,
        AUTHORITY_RANK[packet.authority],
        observed,
        packet.confidence,
        packet.content_sha256,
    )


def _value_hash(packet: EvidencePacket) -> str:
    return _sha256(packet.value)


def _block_from_packet(packet: EvidencePacket, reason: str) -> EvidenceBlock:
    return EvidenceBlock(
        game_id=packet.game_id,
        scope=packet.scope,
        market=packet.market,
        entity_id=packet.entity_id,
        reason=reason,
        fact_type=packet.fact_type,
        subject_id=packet.subject_id,
    )


def resolve_evidence(
    packets: Sequence[EvidencePacket],
    *,
    now: datetime | str,
) -> EvidenceResolution:
    """Resolve evidence deterministically without using acquisition mode as a rank.

    Rules:
    * stale packets never participate;
    * verified beats unverified, then authority rank, then recency/confidence;
    * simultaneous top verified AUTHORITATIVE contradictions fail closed;
    * a strictly newer authoritative fact supersedes older authoritative state;
    * lower-ranked contradictions are recorded, never averaged;
    * verified PRIMARY/AUTHORITATIVE winners may explicitly block matching rows.
    """
    current = _utc(now, "now")
    active: list[EvidencePacket] = []
    rejected_stale: list[str] = []
    for packet in packets:
        if not isinstance(packet, EvidencePacket):
            raise EvidenceError("resolve_evidence requires EvidencePacket objects")
        if packet.expires_at_utc and _utc(packet.expires_at_utc, "expires_at_utc") <= current:
            rejected_stale.append(packet.content_sha256)
            continue
        active.append(packet)

    grouped: dict[tuple[str, str, str, str | None, str | None], list[EvidencePacket]] = {}
    for packet in active:
        grouped.setdefault(packet.fact_key, []).append(packet)

    winners: list[EvidencePacket] = []
    conflicts: list[EvidenceConflict] = []
    blocks: list[EvidenceBlock] = []

    for fact_key in sorted(grouped, key=str):
        group = sorted(grouped[fact_key], key=_sort_key, reverse=True)
        winner = group[0]
        top_priority = _priority(winner)
        same_priority = [packet for packet in group if _priority(packet) == top_priority]
        newest_time = max(_utc(packet.observed_at_utc, "observed_at_utc") for packet in same_priority)
        newest_top = [
            packet for packet in same_priority
            if _utc(packet.observed_at_utc, "observed_at_utc") == newest_time
        ]
        newest_values = {_value_hash(packet) for packet in newest_top}
        same_priority_values = {_value_hash(packet) for packet in same_priority}
        all_values = {_value_hash(packet) for packet in group}

        if (
            len(newest_values) > 1
            and winner.verified
            and winner.authority == "AUTHORITATIVE"
        ):
            broadest = max(newest_top, key=lambda packet: SCOPE_RANK[packet.scope])
            reason = f"EVIDENCE_CONFLICT:{winner.fact_type}:{winner.subject_id}"
            blocks.append(_block_from_packet(broadest, reason))
            conflicts.append(EvidenceConflict(
                fact_key=fact_key,
                severity="BLOCK",
                reason="SIMULTANEOUS_AUTHORITATIVE_FACTS_DISAGREE",
                winner_sha256=None,
                competing_sha256=tuple(sorted(packet.content_sha256 for packet in newest_top)),
                sources=tuple(sorted({packet.source_name for packet in newest_top})),
            ))
            winners.append(winner)
            continue

        winners.append(winner)
        if len(all_values) > 1:
            older_same_priority_conflict = (
                len(same_priority_values) > 1 and len(newest_values) == 1
            )
            if older_same_priority_conflict and winner.verified and winner.authority == "AUTHORITATIVE":
                severity = "INFO"
                reason = "NEWER_AUTHORITATIVE_FACT_SUPERSEDES_OLDER"
            elif len(same_priority_values) > 1:
                severity = "DOWNWEIGHT"
                reason = "EQUAL_PRIORITY_FACTS_DISAGREE_NEWEST_SELECTED"
            else:
                severity = "INFO"
                reason = "LOWER_PRIORITY_FACT_OVERRIDDEN"
            conflicts.append(EvidenceConflict(
                fact_key=fact_key,
                severity=severity,
                reason=reason,
                winner_sha256=winner.content_sha256,
                competing_sha256=tuple(sorted(
                    packet.content_sha256 for packet in group
                    if packet.content_sha256 != winner.content_sha256
                )),
                sources=tuple(sorted({packet.source_name for packet in group})),
            ))

        if (
            winner.gate_action == "BLOCK_MATCHING"
            and winner.verified
            and winner.authority in {"PRIMARY", "AUTHORITATIVE"}
        ):
            blocks.append(_block_from_packet(
                winner,
                f"EVIDENCE_GATE:{winner.fact_type}:{winner.subject_id}",
            ))

    unique_blocks: dict[tuple[str, str, str | None, str | None, str], EvidenceBlock] = {}
    for block in blocks:
        key = (block.game_id, block.scope, block.market, block.entity_id, block.reason)
        unique_blocks[key] = block
    return EvidenceResolution(
        winners=tuple(winners),
        conflicts=tuple(conflicts),
        blocks=tuple(unique_blocks[key] for key in sorted(unique_blocks, key=str)),
        rejected_stale=tuple(sorted(rejected_stale)),
    )


def evidence_resolution_to_dict(resolution: EvidenceResolution) -> dict[str, Any]:
    return {
        "status": resolution.status,
        "winner_count": len(resolution.winners),
        "conflict_count": len(resolution.conflicts),
        "block_count": len(resolution.blocks),
        "rejected_stale_count": len(resolution.rejected_stale),
        "winner_hashes": [packet.content_sha256 for packet in resolution.winners],
        "conflicts": [asdict(conflict) for conflict in resolution.conflicts],
        "blocks": [asdict(block) for block in resolution.blocks],
        "rejected_stale": list(resolution.rejected_stale),
    }


def starter_evidence(
    *,
    game_id: str,
    team_id: str,
    starter_id: str,
    source_name: str,
    observed_at_utc: datetime | str,
    acquisition_mode: str,
    authority: str = "AUTHORITATIVE",
    verified: bool = True,
) -> EvidencePacket:
    """Normalize a starting-pitcher fact. Conflicts apply to the whole game."""
    return EvidencePacket(
        game_id=game_id,
        fact_type="STARTER_ID",
        subject_id=str(team_id),
        value=str(starter_id),
        source_name=source_name,
        observed_at_utc=_utc(observed_at_utc, "observed_at_utc").isoformat(),
        acquisition_mode=acquisition_mode,
        authority=authority,
        verified=verified,
        scope="GAME",
    )


def lineup_status_evidence(
    *,
    game_id: str,
    player_id: str,
    in_starting_lineup: bool,
    source_name: str,
    observed_at_utc: datetime | str,
    acquisition_mode: str,
    authority: str = "AUTHORITATIVE",
    verified: bool = True,
) -> EvidencePacket:
    """Normalize confirmed lineup status; an absent player blocks only that entity."""
    return EvidencePacket(
        game_id=game_id,
        fact_type="STARTING_LINEUP_STATUS",
        subject_id=str(player_id),
        value=bool(in_starting_lineup),
        source_name=source_name,
        observed_at_utc=_utc(observed_at_utc, "observed_at_utc").isoformat(),
        acquisition_mode=acquisition_mode,
        authority=authority,
        verified=verified,
        scope="ENTITY",
        entity_id=str(player_id),
        gate_action="NONE" if in_starting_lineup else "BLOCK_MATCHING",
    )


def market_quote_evidence(
    *,
    game_id: str,
    market: str,
    entity_id: str,
    side: str,
    line: Any,
    american_odds: Any,
    source_name: str,
    observed_at_utc: datetime | str,
    acquisition_mode: str,
    verified: bool,
    expires_at_utc: datetime | str | None = None,
    authority: str = "PRIMARY",
) -> EvidencePacket:
    """Normalize a price quote without converting it into a predictive feature."""
    expiry = None if expires_at_utc is None else _utc(expires_at_utc, "expires_at_utc").isoformat()
    return EvidencePacket(
        game_id=game_id,
        fact_type="MARKET_QUOTE",
        subject_id=f"{str(market).upper()}:{entity_id}:{str(side).upper()}:{line}",
        value={"side": str(side).upper(), "line": line, "american_odds": american_odds},
        source_name=source_name,
        observed_at_utc=_utc(observed_at_utc, "observed_at_utc").isoformat(),
        acquisition_mode=acquisition_mode,
        authority=authority,
        verified=verified,
        scope="MARKET_ENTITY",
        market=str(market).upper(),
        entity_id=str(entity_id),
        expires_at_utc=expiry,
    )
