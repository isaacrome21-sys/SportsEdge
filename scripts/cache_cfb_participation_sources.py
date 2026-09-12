#!/usr/bin/env python3
"""Capture checksum-bound CFB participation sources prospectively."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.participation_source_capture import (
    PARTICIPATION_DATASETS,
    cache_participation_bundle,
    cache_participation_source,
)


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        description="Capture checksum-bound current CFB player participation sources"
    )
    out.add_argument("--season", required=True, type=int)
    out.add_argument("--dataset", choices=tuple(PARTICIPATION_DATASETS))
    out.add_argument("--cache-root", default="artifacts/cfb_forward_participation/source")
    out.add_argument("--self-test", action="store_true")
    return out


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        assert set(PARTICIPATION_DATASETS) == {
            "play_by_play", "play_participants", "player_box", "game_rosters"
        }
        print(json.dumps({
            "status": "SELF_TEST_OK",
            "datasets": sorted(PARTICIPATION_DATASETS),
            "market_data_allowed": False,
            "retroactive_pit_allowed": False,
        }, sort_keys=True))
        return 0
    try:
        if args.dataset:
            rows = (cache_participation_source(
                dataset=args.dataset,
                season=args.season,
                cache_root=args.cache_root,
            ),)
        else:
            rows = cache_participation_bundle(
                season=args.season,
                cache_root=args.cache_root,
            )
        print(json.dumps({
            "status": "CFB_PARTICIPATION_SOURCES_CAPTURED",
            "season": args.season,
            "asset_count": len(rows),
            "assets": rows,
            "model_p_created": False,
            "promotion_authority": False,
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "ERROR",
            "reason": f"{type(exc).__name__}:{exc}",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
