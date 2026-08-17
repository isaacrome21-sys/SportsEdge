#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from pybaseball import statcast

from sportsedge.statcast_daily_source import StatcastSnapshot, aggregate_statcast, snapshot_manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--end-date", default=None)
    p.add_argument("--output-dir", default="artifacts/statcast")
    args = p.parse_args()

    if args.days <= 0 or args.days > 90:
        p.error("--days must be between 1 and 90")
    now = datetime.now(timezone.utc)
    end = date.fromisoformat(args.end_date) if args.end_date else now.date()
    start = end - timedelta(days=args.days - 1)

    frame = statcast(start.isoformat(), end.isoformat(), verbose=False, parallel=False)
    if frame is None or frame.empty:
        raise SystemExit("STATCAST_NO_ROWS")
    rows = frame.where(frame.notna(), None).to_dict(orient="records")
    batter_rows, pitcher_rows = aggregate_statcast(rows, start_date=start, end_date=end, retrieved_at=now)
    snap = StatcastSnapshot(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        retrieved_at=now.isoformat(),
        source="BASEBALL_SAVANT_STATCAST_VIA_PYBASEBALL",
        batter_rows=tuple(batter_rows),
        pitcher_rows=tuple(pitcher_rows),
        raw_pitch_rows=len(rows),
    )

    out_dir = Path(args.output_dir) / snap.end_date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batters.json").write_text(json.dumps(list(snap.batter_rows), indent=2, sort_keys=True, default=str) + "\n")
    (out_dir / "pitchers.json").write_text(json.dumps(list(snap.pitcher_rows), indent=2, sort_keys=True, default=str) + "\n")
    manifest = snapshot_manifest(snap)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
