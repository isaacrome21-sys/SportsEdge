#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.mlb_v7_statsapi_history import finalize_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize MLB V7 StatsAPI history only from complete hash-verified monthly shards.")
    parser.add_argument("--shard-root", required=True)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    report = finalize_history(
        shard_root=Path(args.shard_root), coverage_start=args.start,
        coverage_end=args.end, output_root=Path(args.output_root),
    )
    print(json.dumps({
        "state": report["state"], "required_shard_count": report["required_shard_count"],
        "verified_shard_count": report["verified_shard_count"], "final_game_count": report["final_game_count"],
        "attestation_written": report["attestation_written"], "blocker_count": len(report["blockers"]),
    }, sort_keys=True))
    return 0 if report["state"] == "READY_TO_ATTEST" else 3


if __name__ == "__main__":
    raise SystemExit(main())
