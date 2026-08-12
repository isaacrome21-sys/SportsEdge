"""Durable, append-only decision evidence for SportsEdge automation.

This module is observability only. It records the card SportsEdge already produced;
it must never alter Model_P, Truth Gate status, deployment eligibility, or sizing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class DecisionLedgerError(ValueError):
    pass


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _decision_id(run_id: str, row: Mapping[str, Any]) -> str:
    identity = {
        "run_id": run_id,
        "source_index": row.get("source_index"),
        "game_id": row.get("game_id"),
        "market": row.get("market"),
        "entity_id": row.get("entity_id"),
        "line": row.get("line"),
        "side": row.get("side"),
        "american_odds": row.get("american_odds"),
        "book_key": row.get("book_key"),
    }
    return hashlib.sha256(_stable_json(identity).encode("utf-8")).hexdigest()


def _wager_key(row: Mapping[str, Any]) -> str | None:
    """Stable exact-bet identity across runs and price changes.

    Odds and run_id are deliberately excluded. The book is mandatory: a wager
    at DraftKings and the same line at another book are distinct executions.
    """
    book = str(row.get("book_key") or "").strip()
    game_id = str(row.get("game_id") or "").strip()
    market = str(row.get("market") or "").strip()
    side = str(row.get("side") or "").strip()
    if not (book and game_id and market and side):
        return None
    identity = {
        "book_key": book,
        "game_id": game_id,
        "market": market,
        "entity_id": str(row.get("entity_id") or ""),
        "line": row.get("line"),
        "side": side,
    }
    return hashlib.sha256(_stable_json(identity).encode("utf-8")).hexdigest()


def build_decision_ledger(payload: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise DecisionLedgerError("PAYLOAD_NOT_MAPPING")
    generated = str(payload.get("generated_at_utc") or "").strip()
    if not generated:
        raise DecisionLedgerError("GENERATED_AT_MISSING")
    rid = str(run_id or payload.get("run_id") or generated).strip()
    if not rid:
        raise DecisionLedgerError("RUN_ID_MISSING")
    provider_status = payload.get("provider_status") or []
    if not isinstance(provider_status, list):
        raise DecisionLedgerError("PROVIDER_STATUS_NOT_LIST")
    results = payload.get("results") or []
    if not isinstance(results, list):
        raise DecisionLedgerError("RESULTS_NOT_LIST")

    rows = []
    for raw in results:
        if not isinstance(raw, Mapping):
            raise DecisionLedgerError("RESULT_ROW_NOT_MAPPING")
        row = dict(raw)
        wager_key = _wager_key(row)
        rows.append({
            "decision_id": _decision_id(rid, row),
            "wager_key": wager_key,
            "execution_ready": bool(wager_key) and row.get("bet_status") == "OFFICIAL_BET",
            "run_id": rid,
            "slate_date_ct": payload.get("slate_date_ct"),
            "generated_at_utc": generated,
            "source_index": row.get("source_index"),
            "game_id": row.get("game_id"),
            "market": row.get("market"),
            "entity_id": row.get("entity_id"),
            "line": row.get("line"),
            "side": row.get("side"),
            "book_key": row.get("book_key"),
            "american_odds": row.get("american_odds"),
            "model_p": row.get("model_p"),
            "bet_status": row.get("bet_status"),
            "reason": row.get("reason"),
            "provider_status": provider_status,
        })
    return {
        "schema_version": "sportsedge_decision_ledger_v2",
        "run_id": rid,
        "slate_date_ct": payload.get("slate_date_ct"),
        "generated_at_utc": generated,
        "run_status": payload.get("run_status"),
        "decision_count": len(rows),
        "decisions": rows,
    }


def write_decision_ledger(payload: Mapping[str, Any], path: str | Path, *, run_id: str | None = None) -> dict[str, Any]:
    ledger = build_decision_ledger(payload, run_id=run_id)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ledger


def append_run_history(ledger: Mapping[str, Any], path: str | Path) -> None:
    """Append one immutable compact run record for later CLV/settlement joins."""
    if not isinstance(ledger, Mapping):
        raise DecisionLedgerError("LEDGER_NOT_MAPPING")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "schema_version": ledger.get("schema_version"),
        "run_id": ledger.get("run_id"),
        "slate_date_ct": ledger.get("slate_date_ct"),
        "generated_at_utc": ledger.get("generated_at_utc"),
        "run_status": ledger.get("run_status"),
        "decision_count": ledger.get("decision_count"),
        "decision_ids": [x.get("decision_id") for x in (ledger.get("decisions") or [])],
        "wager_keys": [x.get("wager_key") for x in (ledger.get("decisions") or []) if x.get("wager_key")],
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with p.open("a", encoding="utf-8") as fh:
        fh.write(_stable_json(compact) + "\n")
