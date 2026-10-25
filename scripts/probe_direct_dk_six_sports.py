#!/usr/bin/env python3
"""Read-only six-sport direct DraftKings source probe. No fabricated endpoint IDs."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from sportsedge.draftkings_game_market_source import (
    LEAGUE_IDS, VERIFIED_GAME_LINE_CATEGORY_IDS, DraftKingsGameMarketError, fetch_board,
)
SPORTS = {"NFL": "americanfootball_nfl", "NBA": "basketball_nba",
          "MLB": "baseball_mlb", "CFB": "americanfootball_ncaaf",
          "CBB": "basketball_ncaab", "NHL": "icehockey_nhl"}

def probe(*, fetcher=fetch_board, clock=lambda: datetime.now(timezone.utc)):
    result = {"schema": "sportsedge.dk_direct_probe.v1",
              "captured_at_utc": clock().isoformat(), "sports": {}}
    for sport, key in SPORTS.items():
        if key not in LEAGUE_IDS or key not in VERIFIED_GAME_LINE_CATEGORY_IDS:
            result["sports"][sport] = {"status": "UNVERIFIED_MAPPING"}
            continue
        try:
            board = fetcher(key)
            result["sports"][sport] = {
                "status": "FETCHED", "source_uri": board.source_uri,
                "received_at_utc": board.received_at.isoformat(),
                "market_catalog": sorted({str(m.get("name")).strip() for m in board.payload.get("markets", []) if isinstance(m, dict) and str(m.get("name") or "").strip()}) if isinstance(board.payload.get("markets"), list) else None,
                "payload_markets": len(board.payload["markets"]) if isinstance(board.payload.get("markets"), list) else None,
                "payload_events": len(board.payload["events"])
                    if isinstance(board.payload.get("events"), list) else None}
        except (DraftKingsGameMarketError, OSError, ValueError) as exc:
            result["sports"][sport] = {"status": "UNAVAILABLE",
                                       "reason": type(exc).__name__}
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("artifacts/dk_direct/six_sport_probe.json"))
    args = ap.parse_args()
    report = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
