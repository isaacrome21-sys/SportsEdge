"""Native/manual DraftKings quote intake for MLB HYBRID runs.

This module does not scrape or acquire sportsbook prices. It only normalizes
quotes supplied by the caller and reuses the canonical HYBRID timestamp policy.
INTAKE_STAMPED is presentation freshness only and never evidence for CLV, replay,
Truth Gate, or OFFICIAL status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .mlb_run_machine import (
    TIMESTAMP_SOURCE_INTAKE_STAMPED,
    _prepare_hybrid_quotes,
)
from .source_lineage import canonical_json_sha256

SOURCE = "DRAFTKINGS_NATIVE_MANUAL_INTAKE"
SCHEMA_VERSION = "mlb_dk_hybrid_source_v1"


class MLBDKHybridSourceError(RuntimeError):
    pass


def _is_draftkings_label(value: Any) -> bool:
    text = str(value or "").strip().lower().replace(" ", "")
    return text in {"", "dk", "draftkings", "draftkingsmanual", "manual_input"}


def acquire_dk_hybrid_quotes(
    *,
    quotes: Sequence[Mapping[str, Any]] | None,
    as_of: datetime,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    raw_quotes = list(quotes or [])
    for index, row in enumerate(raw_quotes):
        if not isinstance(row, Mapping):
            raise MLBDKHybridSourceError(f"DK_QUOTE_MUST_BE_OBJECT:quote[{index}]")
        if not _is_draftkings_label(row.get("book_key")) or not _is_draftkings_label(row.get("sportsbook")):
            raise MLBDKHybridSourceError(f"NON_DRAFTKINGS_QUOTE_REJECTED:quote[{index}]")

    normalized = _prepare_hybrid_quotes(raw_quotes, current=as_of)
    intake_stamped = 0
    rows: list[dict[str, Any]] = []
    for row in normalized:
        item = dict(row)
        item["book_key"] = "draftkings_manual"
        item["sportsbook"] = "DraftKings"
        item["quote_source"] = SOURCE
        item["model_p_eligible"] = False
        item["evidence_eligible"] = False
        if item.get("timestamp_source") == TIMESTAMP_SOURCE_INTAKE_STAMPED:
            intake_stamped += 1
        rows.append(item)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "source": SOURCE,
        "quotes": rows,
        "quote_count": len(rows),
        "intake_stamped_count": intake_stamped,
        "provided_timestamp_count": len(rows) - intake_stamped,
        "status": "AVAILABLE" if rows else "NO_QUOTES",
        "model_p_eligible": False,
        "evidence_eligible": False,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
