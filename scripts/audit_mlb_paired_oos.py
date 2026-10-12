#!/usr/bin/env python3
"""Evaluate timestamp-verifiable MLB market-blind pregame paired observations.

Example:
    python scripts/audit_mlb_paired_oos.py --input artifacts/mlb_pit_rows.json \
        --output artifacts/mlb_pit_readout.json

This script never sources bookmaker quotes, recomputes historical lineups,
or opens sealed holdouts. Missing PIT evidence results in BLOCKED_EVIDENCE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.backtest.strict_paired_oos import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-games", type=int, default=300)
    parser.add_argument("--min-series", type=int, default=20)
    args = parser.parse_args(argv)
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate(rows, min_games=args.min_games,
                      min_series=args.min_series)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "n_submitted": result.get("n_submitted", 0),
        "n_verified": result.get("n_verified", 0),
        "n_rejected": result.get("n_rejected", 0),
        "reject_reasons": result.get("reject_reasons", {}),
        "output": str(args.output),
    }, sort_keys=True))
    # Fail closed in automation: cannot promote on a smoke test or
    # interpret insufficient input as success.
    return 0 if result["status"] in {
        "FORECAST_IMPROVEMENT_RESEARCH_ONLY",
        "NO_DEMONSTRATED_FORECAST_IMPROVEMENT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
