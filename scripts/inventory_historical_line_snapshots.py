"""Audit coverage of archived SportsEdge line snapshots without fabricating predictions.

Produces a source inventory, NOT scored historical backtest rows.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sportsedge.line_snapshots import SPORTS, _parse_dt


def inventory(root: Path) -> dict:
    counts = Counter()
    reasons = Counter()
    samples = []
    for path in sorted(root.glob("*/*.jsonl")):
        sport = path.parent.name.lower()
        if sport not in SPORTS:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            counts[sport] += 1
            try:
                record = json.loads(line)
                captured = _parse_dt(record.get("captured_at"))
                if captured is None:
                    raise ValueError("missing capture")
                if record.get("sport", "").lower() != sport:
                    raise ValueError("sport mismatch")
                if not record.get("content_sha256"):
                    raise ValueError("missing content hash")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                reasons[sport + ":INVALID_SNAPSHOT"] += 1
                if len(samples) < 20:
                    samples.append({"path": str(path), "line": line_number, "reason": str(exc)})
    return {
        "report_type": "SNAPSHOT_COVERAGE_INVENTORY_NOT_BACKTEST",
        "production_eligibility_changed": False,
        "snapshot_counts": dict(sorted(counts.items())),
        "invalid_counts": dict(sorted(reasons.items())),
        "invalid_samples": samples,
        "historical_model_rows_generated": 0,
        "backtest_status": "BLOCKED_NEEDS_FROZEN_MODEL_P_AND_PIT_JOIN",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("ledger/line_snapshots"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
