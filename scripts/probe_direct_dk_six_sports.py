#!/usr/bin/env python3
"""Read-only six-sport direct DraftKings source probe. No fabricated endpoint IDs."""
from __future__ import annotations
import argparse
import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
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

def probe(*, fetcher=fetch_board, clock=lambda: datetime.now(timezone.utc), archive_dir=None):
    result = {"schema": "sportsedge.dk_direct_probe.v1",
              "captured_at_utc": clock().isoformat(), "sports": {}}
    for sport, key in SPORTS.items():
        if key not in LEAGUE_IDS or key not in VERIFIED_GAME_LINE_CATEGORY_IDS:
            result["sports"][sport] = {"status": "UNVERIFIED_MAPPING"}
            continue
        try:
            board = fetcher(key)
            if (board.sport_key != key or not isinstance(board.raw, bytes)
                    or not isinstance(board.payload, dict)
                    or board.received_at.tzinfo is None
                    or board.received_at.utcoffset() is None):
                raise ValueError("DK_PROBE_SOURCE_IDENTITY_INVALID")
            source = urlsplit(board.source_uri)
            if (not board.raw or source.scheme != "https"
                    or source.hostname != "sportsbook-nash.draftkings.com"
                    or source.port not in (None, 443)
                    or source.username is not None or source.password is not None):
                raise ValueError("DK_PROBE_SOURCE_URI_OR_RAW_INVALID")
            if json.loads(board.raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON"))) != board.payload:
                raise ValueError("DK_PROBE_RAW_PAYLOAD_MISMATCH")
            raw_archive = None
            if archive_dir is not None:
                destination = Path(archive_dir) / (sport.lower() + "-" + hashlib.sha256(board.raw).hexdigest() + ".json")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and destination.read_bytes() != board.raw:
                    raise ValueError("ARCHIVE_CONFLICT")
                if not destination.exists():
                    with destination.open("xb") as archive:
                        archive.write(board.raw)
                if destination.read_bytes() != board.raw:
                    raise ValueError("ARCHIVE_VERIFY_FAILED")
                raw_archive = str(destination)
            result["sports"][sport] = {
                "raw_archive": raw_archive,
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
                **(selection_linkage(board.payload) or {"unlinked_selections": None, "linked_selections": None, "duplicate_market_ids": None, "duplicate_event_ids": None, "markets_without_event": None}),
                "payload_events": len(board.payload["events"])
                    if isinstance(board.payload.get("events"), list) else None}
        except (DraftKingsGameMarketError, OSError, ValueError, TypeError, AttributeError) as exc:
            result["sports"][sport] = {"status": "UNAVAILABLE",
                                       "reason": type(exc).__name__}
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("artifacts/dk_direct/six_sport_probe.json"))
    ap.add_argument("--archive-dir", type=Path, default=None)
    args = ap.parse_args()
    report = probe(archive_dir=args.archive_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
