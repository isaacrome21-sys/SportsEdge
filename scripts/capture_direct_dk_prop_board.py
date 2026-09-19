#!/usr/bin/env python3
"""DraftKings prop-board snapshot for NFL, CFB, and MLB. Quote discovery only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1"
BOARDS = {
    "americanfootball_nfl": {
        "league_id": 88808,
        "categories": {"TD Scorers": 1003, "Passing Props": 1000, "Receiving Props": 1342, "Rushing Props": 1001},
    },
    "americanfootball_ncaaf": {
        "league_id": 87637,
        "categories": {"TD Scorers": 1003, "Passing Props": 1000, "Receiving Props": 1342, "Rushing Props": 1001},
    },
    "baseball_mlb": {
        "league_id": 84240,
        "categories": {"Batter Props": 743, "Pitcher Props": 1031},
    },
}


def fetch(url: str) -> dict:
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 SportsEdge-DK-Prop-Board/1",
        "Referer": "https://sportsbook.draftkings.com/",
        "Origin": "https://sportsbook.draftkings.com",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/dk_prop_board.json")
    args = parser.parse_args()
    report = {
        "contract": "SPORTSEDGE_DK_PROP_BOARD_V1",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "official_authority": False,
        "model_p_input": False,
        "odds_api_used": False,
        "sports": {},
    }
    for sport, spec in BOARDS.items():
        sport_row = {"league_id": spec["league_id"], "categories": {}}
        for name, cat_id in spec["categories"].items():
            url = f"{ROOT}/leagues/{spec['league_id']}/categories/{cat_id}"
            try:
                payload = fetch(url)
                sport_row["categories"][name] = {
                    "status": "OK",
                    "category_id": cat_id,
                    "events": len(payload.get("events") or []),
                    "markets": len(payload.get("markets") or []),
                    "selections": len(payload.get("selections") or []),
                    "source_uri": url,
                }
            except Exception as exc:
                sport_row["categories"][name] = {
                    "status": "BLOCKED",
                    "category_id": cat_id,
                    "reason": f"{type(exc).__name__}:{exc}",
                    "source_uri": url,
                }
        report["sports"][sport] = sport_row
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "wrote": args.out,
        "official_authority": False,
        "sports": {
            sport: {name: row.get("status") for name, row in spec["categories"].items()}
            for sport, spec in report["sports"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
