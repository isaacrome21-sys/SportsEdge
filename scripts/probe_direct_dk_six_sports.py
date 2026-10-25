#!/usr/bin/env python3
"""Read-only six-sport direct DraftKings source probe. No fabricated endpoint IDs."""
from __future__ import annotations
import argparse
import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from sportsedge.draftkings_game_market_source import (
    LEAGUE_IDS, VERIFIED_GAME_LINE_CATEGORY_IDS, DraftKingsGameMarketError, fetch_board,
)
SPORTS = {"NFL": "americanfootball_nfl", "NBA": "basketball_nba",
          "MLB": "baseball_mlb", "CFB": "americanfootball_ncaaf",
          "CBB": "basketball_ncaab", "NHL": "icehockey_nhl"}

def selection_linkage(payload):
    """Count selection-to-market links; never infer missing IDs or prices."""
    markets = payload.get("markets")
    selections = payload.get("selections")
    if not isinstance(markets, list) or not isinstance(selections, list):
        return None
    ids = {str(m["id"]) for m in markets
           if isinstance(m, dict) and m.get("id") is not None}
    event_ids = {str(e["id"]) for e in payload.get("events", [])
                 if isinstance(e, dict) and e.get("id") is not None} if isinstance(payload.get("events"), list) else None
    return {
        "duplicate_event_ids": (len([e for e in payload["events"]
            if isinstance(e, dict) and e.get("id") is not None]) - len(event_ids))
            if event_ids is not None else None,
        "markets_without_event": sum(1 for m in markets if isinstance(m, dict)
            and (m.get("eventId") is None or str(m["eventId"]) not in event_ids))
            if event_ids is not None else None,
        "unlinked_selections": sum(
            1 for x in selections if isinstance(x, dict)
            and (x.get("marketId") is None or str(x["marketId"]) not in ids)),
        "linked_selections": sum(
            1 for x in selections if isinstance(x, dict)
            and x.get("marketId") is not None and str(x["marketId"]) in ids),
        "duplicate_market_ids": len([
            m for m in markets if isinstance(m, dict) and m.get("id") is not None
        ]) - len(ids),
    }

def probe(*, fetcher=fetch_board, clock=lambda: datetime.now(timezone.utc)):
    result = {"schema": "sportsedge.dk_direct_probe.v1",
              "captured_at_utc": clock().isoformat(), "sports": {}}
    for sport, key in SPORTS.items():
        if key not in LEAGUE_IDS or key not in VERIFIED_GAME_LINE_CATEGORY_IDS:
            result["sports"][sport] = {"status": "UNVERIFIED_MAPPING"}
            continue
        try:
            board = fetcher(key)
            if board.sport_key != key or not isinstance(board.raw, bytes):
                raise ValueError("DK_PROBE_SOURCE_IDENTITY_INVALID")
            result["sports"][sport] = {
                "status": "FETCHED", "source_uri": board.source_uri,
                "quote_jurisdiction": "UNVERIFIED",
                "playable_in_user_jurisdiction": False,
                "quote_timestamp_status": "UNVERIFIED",
                "raw_sha256": hashlib.sha256(board.raw).hexdigest(),
                "raw_size_bytes": len(board.raw),
                "received_at_utc": board.received_at.isoformat(),
                "market_catalog": sorted({str(m.get("name")).strip() for m in board.payload.get("markets", []) if isinstance(m, dict) and str(m.get("name") or "").strip()}) if isinstance(board.payload.get("markets"), list) else None,
                "payload_markets": len(board.payload["markets"]) if isinstance(board.payload.get("markets"), list) else None,
                "market_counts": dict(sorted(Counter(str(m.get("name")).strip() for m in board.payload.get("markets", []) if isinstance(m, dict) and str(m.get("name") or "").strip()).items())) if isinstance(board.payload.get("markets"), list) else None,
                "payload_selections": len(board.payload["selections"]) if isinstance(board.payload.get("selections"), list) else None,
                **(selection_linkage(board.payload) or {"unlinked_selections": None, "linked_selections": None, "duplicate_market_ids": None}),
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
