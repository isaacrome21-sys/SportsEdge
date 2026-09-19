#!/usr/bin/env python3
"""Snapshot current DraftKings game boards with no Odds API.

Writes quote-only rows for NFL, CFB, and MLB moneyline/spread/total.
Does not create Model_P. Does not spend The Odds API.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.draftkings_game_market_source import fetch_board, normalize_board

SPORTS = ("americanfootball_nfl", "americanfootball_ncaaf", "baseball_mlb")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/dk_board_snapshot.json")
    args = parser.parse_args(argv)
    report = {
        "contract": "SPORTSEDGE_DK_BOARD_SNAPSHOT_V1",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "DRAFTKINGS_DIRECT_WEB",
        "odds_api_used": False,
        "model_p_input": False,
        "official_authority": False,
        "sports": {},
        "rows": [],
    }
    for sport in SPORTS:
        try:
            board = fetch_board(sport)
            rows = normalize_board(board)
            report["sports"][sport] = {
                "status": "OK",
                "source_uri": board.source_uri,
                "events": len(board.payload.get("events") or []),
                "normalized_rows": len(rows),
            }
            report["rows"].extend(rows)
        except Exception as exc:
            report["sports"][sport] = {
                "status": "BLOCKED",
                "reason": f"{type(exc).__name__}:{exc}",
            }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "wrote": str(out),
        "rows": len(report["rows"]),
        "sports": {k: v.get("status") for k, v in report["sports"].items()},
        "official_authority": False,
    }, sort_keys=True))
    blocked = [k for k, v in report["sports"].items() if v.get("status") != "OK"]
    return 0 if not blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
