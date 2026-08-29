"""Versioned authoritative CFB entity registry.

Provider aliases never become canonical IDs by inference. Ambiguity fails closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


class CFBEntityResolutionError(ValueError):
    pass


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


@dataclass(frozen=True)
class CFBEntity:
    sportsedge_team_id: str
    canonical_name: str
    classification: str
    aliases: tuple[str, ...]
    conference: str | None = None

    def validate(self) -> "CFBEntity":
        if not self.sportsedge_team_id or not self.canonical_name:
            raise CFBEntityResolutionError("ENTITY_IDENTITY_REQUIRED")
        if self.classification not in {"FBS", "FCS"}:
            raise CFBEntityResolutionError("ENTITY_CLASSIFICATION_INVALID")
        return self


class CFBEntityRegistry:
    def __init__(self, *, version: str, entities: Iterable[CFBEntity]) -> None:
        self.version = str(version or "").strip()
        if not self.version:
            raise CFBEntityResolutionError("ENTITY_REGISTRY_VERSION_REQUIRED")
        rows = tuple(entity.validate() for entity in entities)
        ids = [row.sportsedge_team_id for row in rows]
        if len(ids) != len(set(ids)):
            raise CFBEntityResolutionError("ENTITY_ID_DUPLICATE")
        alias_map: dict[str, str] = {}
        collisions: set[str] = set()
        for row in rows:
            names = (row.canonical_name, *row.aliases)
            for alias in names:
                key = _norm(alias)
                if not key:
                    continue
                previous = alias_map.get(key)
                if previous is None:
                    alias_map[key] = row.sportsedge_team_id
                elif previous != row.sportsedge_team_id:
                    collisions.add(key)
        if collisions:
            raise CFBEntityResolutionError("ENTITY_ALIAS_COLLISION:" + ",".join(sorted(collisions)))
        self._rows = {row.sportsedge_team_id: row for row in rows}
        self._alias_map = alias_map

    def resolve(self, provider_name: str) -> CFBEntity:
        key = _norm(provider_name)
        team_id = self._alias_map.get(key)
        if not key or team_id is None:
            raise CFBEntityResolutionError(f"BLOCKED_ENTITY_RESOLUTION:{provider_name}")
        return self._rows[team_id]

    def classify_matchup(self, home: str, away: str) -> str:
        h = self.resolve(home).classification
        a = self.resolve(away).classification
        if h == "FBS" and a == "FBS":
            return "FBS_FBS"
        if h == "FCS" and a == "FCS":
            return "FCS_FCS"
        return "FBS_FCS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": "CFB_ENTITY_REGISTRY_V1",
            "version": self.version,
            "entities": [asdict(self._rows[key]) for key in sorted(self._rows)],
        }

    def content_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CFBEntityRegistry":
        if str(payload.get("contract") or "") != "CFB_ENTITY_REGISTRY_V1":
            raise CFBEntityResolutionError("ENTITY_REGISTRY_CONTRACT_INVALID")
        rows = []
        for row in payload.get("entities") or []:
            if not isinstance(row, Mapping):
                raise CFBEntityResolutionError("ENTITY_ROW_MAPPING_REQUIRED")
            rows.append(CFBEntity(
                sportsedge_team_id=str(row.get("sportsedge_team_id") or ""),
                canonical_name=str(row.get("canonical_name") or ""),
                classification=str(row.get("classification") or "").upper(),
                aliases=tuple(str(x) for x in (row.get("aliases") or [])),
                conference=str(row.get("conference") or "").strip() or None,
            ))
        return cls(version=str(payload.get("version") or ""), entities=rows)
