#!/usr/bin/env python3
"""Build strictly-as-of market-blind NFL M2 rows for upcoming REG games."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.nfl.live_features import build_nfl_live_feature_payload


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--schedule-file",type=Path,required=True)
    p.add_argument("--pbp-dir",type=Path,required=True)
    p.add_argument("--participation-dir",type=Path,required=True)
    p.add_argument("--depth-dir",type=Path,required=True)
    p.add_argument("--stadium-file",type=Path,required=True)
    p.add_argument("--asof",required=True)
    p.add_argument("--start-season",type=int,default=2016)
    p.add_argument("--current-season",type=int,required=True)
    p.add_argument("--horizon-minutes",type=int,default=120)
    p.add_argument("--min-lead-minutes",type=int,default=45)
    p.add_argument("--out",type=Path,default=Path("artifacts/football/nfl_live_features.json"))
    a=p.parse_args()
    try:
        payload=build_nfl_live_feature_payload(
            schedule_file=a.schedule_file,
            pbp_dir=a.pbp_dir,
            participation_dir=a.participation_dir,
            depth_dir=a.depth_dir,
            stadium_file=a.stadium_file,
            asof=a.asof,
            start_season=a.start_season,
            current_season=a.current_season,
            horizon_minutes=a.horizon_minutes,
            min_lead_minutes=a.min_lead_minutes,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "asof_ts":payload["asof_ts"],
        "source_manifest_sha256":payload["source_manifest_sha256"],
        "completed_game_count":payload["completed_game_count"],
        "replay_game_count":payload["replay_game_count"],
        "target_game_count":payload["target_game_count"],
        "game_ids":[r["game_id"] for r in payload["games"]],
    },sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
