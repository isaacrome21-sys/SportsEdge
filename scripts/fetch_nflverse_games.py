#!/usr/bin/env python3
"""Free nflverse games.csv → timestamped JSON history for Attempt 9."""
from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

NFLVERSE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def fetch() -> tuple[list[dict], str]:
    req = Request(NFLVERSE, headers={"User-Agent": "SportsEdge-NFL-Attempt9/1.0", "Accept": "text/csv"})
    with urlopen(req, timeout=90) as response:
        raw = response.read().decode("utf-8-sig")
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            season = int(row["season"])
            if row.get("game_type", "REG") not in {"REG", "POST"}:
                continue
            if row.get("home_score") in (None, "") or row.get("away_score") in (None, ""):
                continue
            rows.append({
                "id": row.get("game_id") or "",
                "date": row.get("gameday") or "",
                "season": season,
                "week": row.get("week"),
                "home": row["home_team"],
                "away": row["away_team"],
                "hs": int(float(row["home_score"])),
                "as": int(float(row["away_score"])),
                "spread_line": float(row["spread_line"]) if row.get("spread_line") not in (None, "") else None,
                "total_line": float(row["total_line"]) if row.get("total_line") not in (None, "") else None,
                "roof": row.get("roof") or None,
                "temp": row.get("temp") or None,
                "wind": row.get("wind") or None,
                "home_qb": row.get("home_qb_name") or None,
                "away_qb": row.get("away_qb_name") or None,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows, NFLVERSE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    rows, source = fetch()
    payload = {
        "source": source,
        "role": "model",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "game_count": len(rows),
        "games": rows,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"games": len(rows), "retrieved_at_utc": payload["retrieved_at_utc"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
