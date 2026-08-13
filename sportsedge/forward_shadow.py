"""Fail-closed prediction-before-outcome ledger primitives for SportsEdge V6.

A forward-shadow prediction is evidence only when it is created before the
wager/game cutoff and is cryptographically bound to the exact model, feature
contract, source cutoff, and entity identity. Outcomes are attached later by a
separate process; prediction rows are immutable.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "sportsedge_forward_shadow_v1"

class ForwardShadowError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ForwardShadowError("TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise ForwardShadowError(f"ARTIFACT_MISSING:{p}")
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class ShadowPrediction:
    market: str
    game_id: str
    entity_id: str
    side: str
    line: float | None
    model_p: float
    generated_at_utc: str
    cutoff_at_utc: str
    model_artifact_sha256: str
    feature_contract_sha256: str
    source_cutoff: str
    model_version: str
    identity: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def validate(self) -> None:
        market = str(self.market).strip().upper()
        if not market:
            raise ForwardShadowError("MARKET_MISSING")
        if not str(self.game_id).strip() or not str(self.entity_id).strip():
            raise ForwardShadowError("IDENTITY_MISSING")
        if not (0.0 < float(self.model_p) < 1.0):
            raise ForwardShadowError("MODEL_P_INVALID")
        generated = _utc(datetime.fromisoformat(self.generated_at_utc.replace("Z", "+00:00")))
        cutoff = _utc(datetime.fromisoformat(self.cutoff_at_utc.replace("Z", "+00:00")))
        if generated >= cutoff:
            raise ForwardShadowError("PREDICTION_NOT_PREGAME")
        for value, name in (
            (self.model_artifact_sha256, "MODEL_SHA_MISSING"),
            (self.feature_contract_sha256, "FEATURE_CONTRACT_SHA_MISSING"),
            (self.source_cutoff, "SOURCE_CUTOFF_MISSING"),
            (self.model_version, "MODEL_VERSION_MISSING"),
        ):
            if not str(value).strip():
                raise ForwardShadowError(name)

    def row_id(self) -> str:
        self.validate()
        material = {
            "market": self.market.upper(),
            "game_id": str(self.game_id),
            "entity_id": str(self.entity_id),
            "side": str(self.side).upper(),
            "line": self.line,
            "generated_at_utc": self.generated_at_utc,
            "cutoff_at_utc": self.cutoff_at_utc,
            "model_artifact_sha256": self.model_artifact_sha256,
            "feature_contract_sha256": self.feature_contract_sha256,
            "source_cutoff": self.source_cutoff,
            "model_version": self.model_version,
            "identity": dict(self.identity),
        }
        return sha256_bytes(canonical_json(material))

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        out = asdict(self)
        out["schema_version"] = SCHEMA_VERSION
        out["row_id"] = self.row_id()
        out["outcome"] = None
        out["outcome_attached_at_utc"] = None
        return out


def build_manifest(rows: Sequence[Mapping[str, Any]], *, generated_at: datetime) -> dict[str, Any]:
    now = _utc(generated_at)
    ids: list[str] = []
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        rid = str(row.get("row_id") or "")
        if not rid:
            raise ForwardShadowError("ROW_ID_MISSING")
        if rid in seen:
            raise ForwardShadowError("DUPLICATE_ROW_ID")
        if row.get("outcome") is not None or row.get("outcome_attached_at_utc") is not None:
            raise ForwardShadowError("PREDICTION_LEDGER_CONTAINS_OUTCOME")
        seen.add(rid); ids.append(rid); normalized.append(row)
    digest = sha256_bytes(canonical_json(normalized))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "prediction_count": len(normalized),
        "row_ids_sha256": sha256_bytes(canonical_json(ids)),
        "predictions_sha256": digest,
        "outcomes_present": False,
    }


def write_prediction_ledger(rows: Sequence[ShadowPrediction], *, output: str | Path, manifest: str | Path, generated_at: datetime | None = None) -> tuple[Path, Path]:
    now = _utc(generated_at or datetime.now(timezone.utc))
    payload = [row.to_dict() for row in rows]
    out = Path(output); man = Path(manifest)
    out.parent.mkdir(parents=True, exist_ok=True); man.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical_json(payload))
    m = build_manifest(payload, generated_at=now)
    m["ledger_file_sha256"] = sha256_file(out)
    man.write_bytes(canonical_json(m))
    return out, man
