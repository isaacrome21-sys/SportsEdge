#!/usr/bin/env python3
"""Fail-closed admission of externally generated historical research JSONL.

This is NOT a historical data collector or model price adapter. It only admits
rows with explicit provenance; blocked rows are recorded separately.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.research.multi_market_backtest import BinaryResearchRow, ResearchBacktestError


def timestamp(value: object) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt


def admit(row: dict) -> str | None:
    try:
        if type(row.get("outcome")) is not int or row["outcome"] not in (0, 1):
            return "OUTCOME_NOT_CANONICAL_BINARY"
        BinaryResearchRow.from_mapping(row)
        required = ("source_id", "source_url", "model_version", "model_run_id",
                    "feature_receipt_ts", "prediction_receipt_ts",
                    "quote_source", "quote_receipt_ts", "outcome_source")
        for key in required:
            if not isinstance(row.get(key), str) or not row[key].strip():
                return "MISSING_" + key.upper()
        feature = timestamp(row["feature_receipt_ts"])
        prediction = timestamp(row["prediction_receipt_ts"])
        quote = timestamp(row["quote_receipt_ts"])
        decision = timestamp(row["decision_ts"])
        start = timestamp(row["event_start_ts"])
        if decision > datetime.now(timezone.utc):
            return "DECISION_IN_FUTURE"
        if feature > decision or prediction > decision or quote > decision:
            return "RECEIPT_AFTER_DECISION"
        if decision >= start:
            return "DECISION_NOT_BEFORE_EVENT"
        if row.get("offered_decimal") is None:
            return "MISSING_OFFERED_PRICE"
        if row.get("benchmark_p") is None:
            return "MISSING_PAIRED_BENCHMARK"
        if row.get("outcome") is None:
            return "PUSH_VOID_OR_UNSETTLED_REQUIRES_SEPARATE_SETTLEMENT"
    except (ResearchBacktestError, ValueError, TypeError, KeyError) as exc:
        return "INVALID_ROW:" + str(exc)
    return None


def run(input_path: Path, accepted_path: Path, blocked_path: Path) -> dict:
    if accepted_path.resolve() == blocked_path.resolve() or input_path.resolve() in (accepted_path.resolve(), blocked_path.resolve()):
        raise ValueError("INPUT_AND_OUTPUT_PATHS_MUST_BE_DISTINCT")
    if accepted_path.is_dir() or blocked_path.is_dir():
        raise ValueError("OUTPUT_PATH_IS_DIRECTORY")
    accepted, blocked = [], []
    seen = set()
    with input_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("ROW_NOT_OBJECT")
                reason = admit(row)
                identity = (row.get("sport"), row.get("market"), row.get("event_id"),
                            row.get("decision_ts"))
                if reason is None and identity in seen:
                    reason = "DUPLICATE_SELECTION_DECISION"
                if reason:
                    blocked.append({"line": line_number, "reason": reason, "row": row})
                else:
                    seen.add(identity)
                    accepted.append(row)
            except (ValueError, TypeError) as exc:
                blocked.append({"line": line_number, "reason": "INVALID_JSON:" + str(exc)})
    for path, records in ((accepted_path, accepted), (blocked_path, blocked)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")
    return {"accepted": len(accepted), "blocked": len(blocked)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--blocked", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.accepted, args.blocked), sort_keys=True))


if __name__ == "__main__":
    main()
