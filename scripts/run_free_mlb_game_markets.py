#!/usr/bin/env python3
"""Fetch free MLB ML/RL/totals for context/RUN-IT ingress without paid calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from sportsedge.free_game_market_acquisition import acquire_mlb_game_markets_free_first
from sportsedge.mlb_source import fetch_schedule


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="MLB slate date YYYY-MM-DD")
    p.add_argument("--required-book", default=None)
    p.add_argument("--out", default="artifacts/free_mlb_game_markets.json")
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    schedule = fetch_schedule(args.date, now=now)
    routed = acquire_mlb_game_markets_free_first(
        schedule=schedule,
        now=now,
        required_book=args.required_book,
        paid_fetch=None,
    )
    payload = {
        "schema": "SPORTSEDGE_FREE_GAME_MARKETS_V1",
        "generated_at_utc": now.isoformat(),
        "slate_date": args.date,
        "required_book": args.required_book,
        "quotes": list(routed.quotes),
        "rejected": list(routed.rejected),
        "authority": "MARKET_CONTEXT_ONLY",
        "model_p": None,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }
    from pathlib import Path
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=str, indent=2) + "\n")
    print(json.dumps({"quotes": len(routed.quotes), "rejected": len(routed.rejected), "out": str(path)}))
    return 0 if routed.quotes else 2


if __name__ == "__main__":
    raise SystemExit(main())
