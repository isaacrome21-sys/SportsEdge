#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path

from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="artifacts/manual_mlb_snapshot_card.json")
    p.add_argument("--history-cache-dir", default=".cache/mlb-history")
    args = p.parse_args()
    snapshot = json.loads(Path(args.input).read_text())
    payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
