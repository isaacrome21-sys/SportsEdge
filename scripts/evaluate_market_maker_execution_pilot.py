#!/usr/bin/env python3
"""Evaluate preregistered stale-price execution-feasibility checkpoints.

The 10/20-attempt pilot answers only whether the lane is operationally executable.
It cannot establish betting edge, Model_P, promotion, staking, or OFFICIAL status.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_POLICY = "config/market_maker_radar_v2.json"
RECORD_TYPE = "MARKET_MAKER_RADAR_EXECUTION_ATTEMPT_V1"


def wilson_upper(successes: int, n: int, z: float = 1.959963984540054) -> float:
    if n <= 0:
        return 1.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return min(1.0, center + half)


def load_attempts(root: Path) -> list[dict[str, Any]]:
    base = root / "archive" / "market-maker-radar" / "execution-attempts"
    if not base.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("record_type") != RECORD_TYPE:
            continue
        rows.append(payload)
    rows.sort(key=lambda row: (str(row.get("attempted_at") or ""), str(row.get("attempt_id") or "")))
    return rows


def evaluate_checkpoint(rows: Sequence[Mapping[str, Any]], checkpoint: int, rule: Mapping[str, Any]) -> dict[str, Any]:
    sample = list(rows[:checkpoint])
    durable = sum(1 for row in sample if bool(row.get("durable_fill")))
    requested = sum(float(row.get("stake_requested_units") or 0.0) for row in sample)
    accepted = sum(float(row.get("stake_accepted_units") or 0.0) for row in sample)
    acceptance_ratio = accepted / requested if requested > 0 else 0.0
    upper = wilson_upper(durable, checkpoint)
    fill_stop = upper < float(rule["stop_if_durable_fill_wilson_95_upper_bound_below"])
    stake_stop = acceptance_ratio < float(rule["stop_if_aggregate_stake_acceptance_ratio_below"])
    return {
        "checkpoint_n": checkpoint,
        "durable_fills": durable,
        "durable_fill_rate": durable / checkpoint,
        "durable_fill_wilson_95_upper": upper,
        "stake_requested_units": requested,
        "stake_accepted_units": accepted,
        "aggregate_stake_acceptance_ratio": acceptance_ratio,
        "fill_stop_triggered": fill_stop,
        "stake_stop_triggered": stake_stop,
        "decision": "STOP_OPERATIONAL_PILOT" if fill_stop or stake_stop else "PASS_CONTINUE_COLLECTION",
        "edge_evidence": False,
        "promotion_authority": False,
        "staking_authority": False
    }


def evaluate_book(book: str, rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    pilot = policy["execution_pilot"]
    checkpoints: list[dict[str, Any]] = []
    stop_at: int | None = None
    for n in pilot["checkpoints"]:
        n = int(n)
        if len(rows) < n:
            continue
        result = evaluate_checkpoint(rows, n, pilot["stop_rules"][f"at_{n}"])
        checkpoints.append(result)
        if result["decision"] == "STOP_OPERATIONAL_PILOT" and stop_at is None:
            stop_at = n
    protocol_violation = stop_at is not None and len(rows) > stop_at
    if stop_at is not None:
        state = "STOP_OPERATIONAL_PILOT"
    elif len(rows) < int(pilot["checkpoints"][0]):
        state = "COLLECT_TO_FIRST_CHECKPOINT"
    elif len(rows) < int(pilot["checkpoints"][-1]):
        state = "COLLECT_TO_NEXT_CHECKPOINT"
    else:
        state = "PILOT_CHECKPOINTS_COMPLETE_NO_EDGE_CLAIM"
    return {
        "soft_book": book,
        "attempt_count": len(rows),
        "state": state,
        "stop_at_checkpoint": stop_at,
        "attempts_after_stop_protocol_violation": protocol_violation,
        "checkpoints": checkpoints
    }


def evaluate(rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    if not rows:
        return {
            "state": policy["execution_pilot"]["status_without_attempts"],
            "attempt_count": 0,
            "books": [],
            "purpose": policy["execution_pilot"]["purpose"],
            "edge_evidence": False,
            "model_p_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
            "official_authority": False
        }
    by_book: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_book.setdefault(str(row.get("soft_book") or "UNKNOWN").lower(), []).append(row)
    books = [evaluate_book(book, by_book[book], policy) for book in sorted(by_book)]
    any_stop = any(item["state"] == "STOP_OPERATIONAL_PILOT" for item in books)
    return {
        "state": "STOP_OPERATIONAL_PILOT" if any_stop else "EXECUTION_EVIDENCE_ACCRUING",
        "attempt_count": len(rows),
        "evaluation_scope": "PER_SOFT_BOOK",
        "books": books,
        "purpose": policy["execution_pilot"]["purpose"],
        "formal_edge_checkpoints": policy["execution_pilot"]["formal_edge_evaluation_unchanged"],
        "edge_evidence": False,
        "model_p_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    report = evaluate(load_attempts(Path(args.ledger_root)), policy)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
