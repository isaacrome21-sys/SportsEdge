#!/usr/bin/env python3
"""Evaluate chronological held-out research probabilities, not betting authority.

Usage: python scripts/audit_research_replay_pit.py INPUT.jsonl --holdout-start ISO --output REPORT.json
Requires externally authenticated source receipts before results can support
CLV, ROI or model promotion. No historical records are bundled or inferred.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sportsedge.research.multi_market_backtest import ResearchBacktestError, summarize_binary_market
from sportsedge.research.pit_replay_gate import PITReplayError, partition_chronological_replay


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSONL rows with PIT and settlement metadata")
    parser.add_argument("--holdout-start", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
        split = partition_chronological_replay(rows, holdout_start=args.holdout_start)
        grouped = defaultdict(list)
        for row in split["holdout"]:
            # Do not accept unauthenticated benchmark, quote, or CLV values.
            scrubbed = dict(row, benchmark_p=None, offered_decimal=None, clv_pct=None, selected=False)
            grouped[(row["sport"].upper(), row["market"].upper(), row["model_version"])].append(scrubbed)
        markets = []
        for (sport, market, version), values in sorted(grouped.items()):
            try:
                summary = summarize_binary_market(values)
                status, blocker = "EVALUATED_RESEARCH_ONLY", None
            except ResearchBacktestError as exc:
                summary, status, blocker = None, "INSUFFICIENT_DATA", str(exc)
            markets.append({"sport": sport, "market": market, "model_version": version,
                            "status": status, "blocker": blocker, "summary": summary,
                            "clv_roi_status": "UNAVAILABLE_AUTHENTICATED_QUOTES_REQUIRED"})
        report = {"report_type": "CHRONOLOGICAL_PIT_METADATA_REPLAY", "production_eligible": False,
                  "provenance": split["provenance"], "cutoff": split["cutoff"],
                  "train_n": split["train_n"], "holdout_n": split["holdout_n"],
                  "markets": markets}
    except (OSError, json.JSONDecodeError, PITReplayError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
