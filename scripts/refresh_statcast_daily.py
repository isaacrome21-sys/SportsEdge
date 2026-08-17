#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sportsedge.statcast_daily_source import fetch_daily_statcast, snapshot_manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--end-date", default=None)
    p.add_argument("--output-dir", default="artifacts/statcast")
    args = p.parse_args()

    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    now = datetime.now(timezone.utc)
    snap = fetch_daily_statcast(end_date=end_date, days=args.days, now=now)

    out_dir = Path(args.output_dir) / snap.end_date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batters.json").write_text(json.dumps(list(snap.batter_rows), indent=2, sort_keys=True) + "\n")
    (out_dir / "pitchers.json").write_text(json.dumps(list(snap.pitcher_rows), indent=2, sort_keys=True) + "\n")
    manifest = snapshot_manifest(snap)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
