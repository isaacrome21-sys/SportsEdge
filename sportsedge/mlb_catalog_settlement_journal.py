"""Create-only content-addressed persistence for MLB catalog settlement records."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .mlb_catalog_prediction_settlement import CATALOG_SETTLEMENT_SCHEMA_VERSION, MLBCatalogSettlementError
from .runtime import parse_timestamp


@dataclass(frozen=True)
class CatalogSettlementWriteResult:
    path: str
    settlement_sha256: str
    prediction_journal_sha256: str
    prediction_count: int
    resolved_count: int
    unresolved_count: int
    created: bool


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MLBCatalogSettlementError("settlement payload is not canonical JSON") from exc


def write_catalog_prediction_settlement(
    record: Mapping[str, Any],
    *,
    root: str | Path = "artifacts/prediction_settlement",
) -> CatalogSettlementWriteResult:
    if not isinstance(record, Mapping):
        raise MLBCatalogSettlementError("settlement record must be an object")
    if str(record.get("schema_version") or "") != CATALOG_SETTLEMENT_SCHEMA_VERSION:
        raise MLBCatalogSettlementError("unsupported catalog settlement schema")
    outcomes = record.get("outcomes")
    if not isinstance(outcomes, list):
        raise MLBCatalogSettlementError("settlement outcomes must be a list")
    try:
        prediction_count = int(record.get("prediction_count"))
        resolved_count = int(record.get("resolved_count"))
        unresolved_count = int(record.get("unresolved_count"))
    except (TypeError, ValueError) as exc:
        raise MLBCatalogSettlementError("settlement counters invalid") from exc
    if prediction_count != len(outcomes) or resolved_count + unresolved_count != prediction_count:
        raise MLBCatalogSettlementError("settlement counters mismatch")
    journal_sha = str(record.get("prediction_journal_sha256") or "").strip().lower()
    if len(journal_sha) != 64 or any(ch not in "0123456789abcdef" for ch in journal_sha):
        raise MLBCatalogSettlementError("prediction_journal_sha256 invalid")

    canonical = _bytes(dict(record))
    settlement_sha = hashlib.sha256(canonical).hexdigest()
    raw = canonical + b"\n"
    settled_at = parse_timestamp(record.get("settled_at_utc"))
    stamp = settled_at.strftime("%Y%m%dT%H%M%S.%fZ")
    slate_date = str(record.get("slate_date_ct") or "").strip()
    if not slate_date:
        raise MLBCatalogSettlementError("slate_date_ct required")
    directory = Path(root) / slate_date
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stamp}_{settlement_sha}.json"

    created = False
    try:
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        created = True
    except FileExistsError:
        if target.read_bytes() != raw:
            raise MLBCatalogSettlementError("immutable settlement path collision")

    return CatalogSettlementWriteResult(
        path=str(target),
        settlement_sha256=settlement_sha,
        prediction_journal_sha256=journal_sha,
        prediction_count=prediction_count,
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        created=created,
    )
