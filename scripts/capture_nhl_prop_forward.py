#!/usr/bin/env python3
"""Capture preregistered NHL prop predictions before puck drop.

Input probabilities must already exist in the source payload.  This command does
not query a sportsbook, create a baseline, alter Model_P, or settle outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sportsedge.sports.nhl.prop_prediction_capture import (
    append_receipts,
    receipts_from_source,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    receipts = receipts_from_source(source_bytes)
    count = append_receipts(args.output, receipts)
    summary = {
        "status": "CAPTURED_PREPUCK",
        "rows_appended": count,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "output": str(args.output),
        "keys": [list(receipt.key) for receipt in receipts],
        "captured_at": sorted({receipt.captured_at for receipt in receipts}),
        "authority": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
