#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

from sportsedge.mlb_v7_bullpen_park_sources import bullpen_usage_rows, park_raw_rows
from sportsedge.mlb_v7_statsapi_history import write_json, write_jsonl
from sportsedge.mlb_v7_travel_history import BASE, _get_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe official MLB final feed for V7 bullpen and park raw source rows.")
    parser.add_argument("--game-id", type=int, default=778485)
    parser.add_argument("--output-root", default="artifacts/mlb-v7-bullpen-park-probe")
    args = parser.parse_args()
    root = Path(args.output_root)
    url = f"{BASE}/api/v1.1/game/{args.game_id}/feed/live"
    feed = _get_json(url)
    bullpen = bullpen_usage_rows(feed)
    park = park_raw_rows(feed)
    raw_sha = write_json(root / "raw/feed.json", feed)
    bullpen_sha = write_jsonl(root / "normalized/BULLPEN_USAGE.jsonl", bullpen)
    park_sha = write_jsonl(root / "normalized/PARK_RAW.jsonl", park)
    report = {
        "contract": "SPORTSEDGE_MLB_V7_BULLPEN_PARK_SOURCE_PROBE_V1",
        "game_id": args.game_id,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "bullpen": {
            "source_class": "BULLPEN_USAGE",
            "row_count": len(bullpen),
            "teams": sorted({row.team_id for row in bullpen}),
            "pitch_count_total": sum(row.pitches for row in bullpen),
            "fields": ["game_id", "team_id", "pitcher_id", "pitches", "game_start_time", "final_at"],
            "semantics": {"point_in_time": True, "final_before_decision": True},
            "evidence_sha256": bullpen_sha,
        },
        "park": {
            "source_class": "PARK_RAW",
            "row_count": len(park),
            "runs": sum(row.runs for row in park),
            "plate_appearances": sum(row.plate_appearances for row in park),
            "home_runs": sum(row.home_runs for row in park),
            "batter_stands": sorted({row.batter_stand for row in park}),
            "fields": ["season", "venue_id", "runs", "plate_appearances", "home_runs", "batter_stand", "game_id", "play_index", "game_start_time", "final_at"],
            "semantics": {"point_in_time": True, "recompute_from_prior_season_raw": True, "later_revised_values_forbidden": True},
            "evidence_sha256": park_sha,
        },
        "raw_feed_sha256": raw_sha,
        "attestation_written": False,
        "candidate_training_allowed": False,
        "promotion_authority": False,
        "blockers": ["FULL_2023_2025_COVERAGE_NOT_COLLECTED", "REDUCED_FEATURE_CONTRACT_NOT_FROZEN"],
    }
    write_json(root / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
