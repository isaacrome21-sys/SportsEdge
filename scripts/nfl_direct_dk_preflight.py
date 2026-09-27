#!/usr/bin/env python3
"""Fail-closed diagnostic for the prospective direct DraftKings NFL transport.

This proves transport + normalization health only. It does not create, rewrite,
or satisfy confirmation evidence and grants no Model_P/Truth-Gate/OFFICIAL
status.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.nfl_direct_capture_source import DirectCaptureError, acquire_board, game_rows_direct


def main() -> int:
    try:
        transport = acquire_board()
        rows = game_rows_direct(transport, week_of=lambda _dt: None)
    except Exception as exc:
        print(json.dumps({
            "state": "DIRECT_DK_UNAVAILABLE",
            "error_class": type(exc).__name__,
            "error": str(exc),
            "evidence_authority": False,
        }, sort_keys=True))
        return 2

    healthy = bool(rows) and all(
        row.get("spread", {}).get("status") == "OK"
        and row.get("total", {}).get("status") == "OK"
        for row in rows
    )
    print(json.dumps({
        "state": "DIRECT_DK_HEALTHY" if healthy else "DIRECT_DK_BOARD_UNADMITTED",
        "source_class": transport.get("source_class"),
        "raw_sha256": transport.get("raw_sha256"),
        "games": len(rows),
        "two_sided_games": sum(
            1 for row in rows
            if row.get("spread", {}).get("status") == "OK"
            and row.get("total", {}).get("status") == "OK"
        ),
        "evidence_authority": False,
    }, sort_keys=True))
    return 0 if healthy else 3


if __name__ == "__main__":
    raise SystemExit(main())
