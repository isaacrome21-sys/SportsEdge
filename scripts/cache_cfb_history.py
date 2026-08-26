#!/usr/bin/env python3
"""Cache checksum-bound SportsDataverse CFB historical assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.history_cache import (
    cache_many,
    parse_season_spec,
    resolve_datasets,
)


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        description="Cache checksum-bound SportsDataverse CFB historical assets"
    )
    out.add_argument("--dataset", action="append", default=[])
    out.add_argument("--seasons", action="append", default=[])
    out.add_argument("--cache-root", default="artifacts/cfb_history")
    out.add_argument("--allow-benchmark", action="store_true")
    out.add_argument("--self-test", action="store_true")
    return out


def main() -> int:
    args = parser().parse_args()
    if args.self_test:
        assert parse_season_spec(["2022:2024"]) == (2022, 2023, 2024)
        names = resolve_datasets(["predictive"])
        assert "betting" not in names
        assert "play_by_play" in names
        print(
            json.dumps(
                {
                    "status": "SELF_TEST_OK",
                    "predictive_dataset_count": len(names),
                    "market_data_prohibited": True,
                }
            )
        )
        return 0

    try:
        seasons = parse_season_spec(args.seasons)
        datasets = resolve_datasets(
            args.dataset,
            allow_benchmark=args.allow_benchmark,
        )
        rows = cache_many(
            datasets=datasets,
            seasons=seasons,
            cache_root=args.cache_root,
            allow_benchmark=args.allow_benchmark,
        )
        print(
            json.dumps(
                {
                    "status": "CACHED",
                    "asset_count": len(rows),
                    "assets": rows,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "reason": f"{type(exc).__name__}:{exc}",
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
