#!/usr/bin/env python3
"""Audit normalized MLB V8 OddsPapi PIT rows for replay-ready decision/close evidence.

The audit is deliberately readiness-only. It does not run a model, set an edge
floor, change eligibility, or grant promotion authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.mlb.paired_replay_readiness import audit_paired_replay_readiness  # noqa: E402

PAIR_MAX_SKEW_SECONDS = 30.0
SOURCE = "ODDSPAPI_HISTORICAL"
SCHEMA = "MLB_V8_ODDSPAPI_PIT_PAIR_V1"


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_pairs(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        reasons: list[str] = []
        if row.get("schema") != SCHEMA:
            reasons.append("SCHEMA_MISMATCH")
        if row.get("source") != SOURCE:
            reasons.append("SOURCE_MISMATCH")
        if row.get("replay_quote_fresh_180s") is not True:
            reasons.append("DECISION_QUOTE_NOT_REPLAY_FRESH")
        if row.get("close_available") is not True:
            reasons.append("CLOSE_MISSING")
        if row.get("close_after_decision") is not True:
            reasons.append("CLOSE_NOT_AFTER_DECISION")
        decision_skew = _float(row.get("decision_pair_skew_seconds"))
        close_skew = _float(row.get("close_pair_skew_seconds"))
        if decision_skew is None or decision_skew > PAIR_MAX_SKEW_SECONDS:
            reasons.append("DECISION_PAIR_SKEW_INVALID")
        if close_skew is None or close_skew > PAIR_MAX_SKEW_SECONDS:
            reasons.append("CLOSE_PAIR_SKEW_INVALID")
        history_sha = str(row.get("history_sha256") or "").strip().lower()
        if len(history_sha) != 64 or any(c not in "0123456789abcdef" for c in history_sha):
            reasons.append("HISTORY_SHA256_INVALID")
        if reasons:
            rejected.append({"index": index, "fixture_id": row.get("fixture_id"), "reasons": reasons})
            continue

        event_start = row.get("first_pitch_utc")
        identity_base = {
            "event_id": str(row.get("fixture_id") or ""),
            "market": str(row.get("market_id") or ""),
            "book": str(row.get("bookmaker") or ""),
            "threshold": row.get("handicap"),
            "provenance": "oddspapi_historical_provider_snapshot",
            "source_sha256": history_sha,
        }
        for side in ("a", "b"):
            selection = str(row.get(f"outcome_{side}_id") or row.get(f"outcome_{side}_name") or "")
            pairs.append({
                "event_start": event_start,
                "decision": {
                    **identity_base,
                    "selection": selection,
                    "observed_at": row.get(f"outcome_{side}_quote_utc"),
                    "price": row.get(f"outcome_{side}_decimal"),
                },
                "close": {
                    **identity_base,
                    "selection": selection,
                    "observed_at": row.get(f"close_outcome_{side}_quote_utc"),
                    "price": row.get(f"close_outcome_{side}_decimal"),
                },
            })
    return pairs, rejected


def audit_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    pairs, rejected = normalized_pairs(rows)
    result = audit_paired_replay_readiness(pairs)
    result["normalized_source_schema"] = SCHEMA
    result["normalized_source"] = SOURCE
    result["rejected_source_row_count"] = len(rejected)
    result["source_row_rejections"] = rejected
    if rejected:
        result["status"] = "BLOCKED_PAIRED_MARKET_EVIDENCE"
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SystemExit(f"MLB_V8_PIT_ROW_NOT_OBJECT:{number}")
        rows.append(payload)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=Path("artifacts/mlb_v8_replay_archive/oddspapi_pit/pit_pairs.jsonl"))
    ap.add_argument("--output", type=Path, default=Path("artifacts/mlb_v8_replay_archive/oddspapi_pit/paired_replay_readiness.json"))
    args = ap.parse_args()
    try:
        rows = _load_jsonl(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("MLB_V8_PAIRED_REPLAY_INPUT_UNREADABLE") from exc
    result = audit_rows(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READY_FOR_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
