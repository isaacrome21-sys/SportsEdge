#!/usr/bin/env python3
"""Assemble the forward-capture archive and run the strict evaluator.

Reads captures + settlements from the archive, joins them into evaluator
rows (unsettled and push records are reported as excluded, never silently
dropped), and calls sportsedge.backtest.strict_paired_oos.evaluate
UNMODIFIED with its default sample bar (300 games / 20 series). Until the
archive genuinely accumulates that sample with zero rejected rows, the
expected statuses are BLOCKED_EVIDENCE or INSUFFICIENT_OOS — that is the
system working as designed, not a failure of this script.

Example:
    python scripts/evaluate_strict_forward_capture.py \
        --archive-dir archive/strict-forward-capture \
        --output artifacts/strict_forward_capture_readout.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.backtest import forward_capture as fc
from sportsedge.backtest.strict_paired_oos import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path,
                        default=Path("archive") / fc.ARCHIVE_DIRNAME)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    rows, excluded = fc.assemble_rows(args.archive_dir)
    result = evaluate(rows)
    payload = {"evaluator": result, "excluded": excluded,
               "archive_dir": str(args.archive_dir)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True)
                           + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "n_rows_assembled": len(rows),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "output": str(args.output),
    }, indent=2, sort_keys=True))
    return 0 if result["status"] in {
        "FORECAST_IMPROVEMENT_RESEARCH_ONLY",
        "NO_DEMONSTRATED_FORECAST_IMPROVEMENT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
