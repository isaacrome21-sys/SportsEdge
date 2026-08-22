from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sportsedge.mlb.nrfi_market_consensus import clv_probability_delta


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n")


def entry_record(
    *,
    event_id: str,
    side: str,
    offered_american: int,
    model_prob: float,
    consensus_prob: float,
    edge_prob: float,
    expected_value: float,
    books_used: int,
    dispersion: float,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    side = side.upper()
    if side not in {"NRFI", "YRFI"}:
        raise ValueError("side must be NRFI or YRFI")
    return {
        "record_type": "ENTRY",
        "event_id": event_id,
        "side": side,
        "captured_at_utc": captured_at_utc or _now_iso(),
        "offered_american": offered_american,
        "model_prob": model_prob,
        "consensus_prob": consensus_prob,
        "model_market_edge": edge_prob,
        "expected_value": expected_value,
        "books_used": books_used,
        "market_dispersion": dispersion,
        "promotion_evidence": False,
    }


def close_record(
    *,
    event_id: str,
    side: str,
    entry_consensus_prob: float,
    closing_consensus_prob: float,
    closing_at_utc: str | None = None,
) -> dict[str, Any]:
    side = side.upper()
    return {
        "record_type": "CLOSE",
        "event_id": event_id,
        "side": side,
        "captured_at_utc": closing_at_utc or _now_iso(),
        "entry_consensus_prob": entry_consensus_prob,
        "closing_consensus_prob": closing_consensus_prob,
        "clv_probability_delta": clv_probability_delta(entry_consensus_prob, closing_consensus_prob, side),
        "promotion_evidence": False,
    }
