#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_history_cache import MLBHistoryCachedOpener
from sportsedge.mlb_pitcher_k_historical_materializer import (
    FROZEN_SEASONS,
    HistoricalStatcastArchive,
    combine_seasons,
    fetch_season_schedule,
    materialize_season,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize PIT-safe 2023-2025 MLB pitcher-K candidate rows."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", default=".cache/mlb-pitcher-k-history")
    parser.add_argument("--statcast-chunk-days", type=int, default=45)
    args = parser.parse_args()

    # 2023-2025 are immutable historical seasons. Using a 2026 target marker lets
    # the existing gameLog cache share each immutable player/team season response.
    opener = MLBHistoryCachedOpener(
        target_date=date(2026, 1, 1),
        cache_dir=args.cache_dir,
    )
    source = MLBGenericHistorySource(opener=opener)
    results = []
    for season in FROZEN_SEASONS:
        schedule = fetch_season_schedule(season, opener=opener)
        archive = HistoricalStatcastArchive.fetch_season(
            season,
            chunk_days=args.statcast_chunk_days,
        )
        result = materialize_season(
            season=season,
            source=source,
            archive=archive,
            schedule_payload=schedule,
        )
        results.append(result)
        print(
            json.dumps(
                {
                    "season": season,
                    "targets": result["target_count"],
                    "eligible": result["eligible_row_count"],
                    "excluded": result["excluded_row_count"],
                },
                sort_keys=True,
            )
        )

    payload = combine_seasons(results)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"row_count": payload["row_count"], "output": str(destination)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
