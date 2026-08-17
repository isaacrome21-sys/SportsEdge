#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path

from sportsedge.canonical_manual_mlb import run_canonical_manual_mlb
from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="artifacts/manual_mlb_snapshot_card.json")
    p.add_argument("--history-cache-dir", default=".cache/mlb-history")
    args = p.parse_args()
    snapshot = json.loads(Path(args.input).read_text())
    if isinstance(snapshot, dict) and isinstance(snapshot.get("rows"), list):
        payload = run_canonical_manual_mlb(snapshot["rows"], history_cache_dir=args.history_cache_dir)
    elif isinstance(snapshot, list):
        payload = run_canonical_manual_mlb(snapshot, history_cache_dir=args.history_cache_dir)
    else:
        payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
