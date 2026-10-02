#!/usr/bin/env python3
"""Emit the complete MLB side, total, and prop presentation board.

Input is a JSON object with a ``rows`` list of already-priced engine or research
rows. Missing catalog families are retained as explicit blockers. This script
does not fit a model or grant OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.mlb_full_board import build_mlb_full_board


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SystemExit("MLB_FULL_BOARD_INPUT_ROWS_REQUIRED")
    board = build_mlb_full_board(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(board["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
