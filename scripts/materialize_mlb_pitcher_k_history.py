#!/usr/bin/env python3
"""Materialize frozen 2023-2025 MLB pitcher-K historical rows.

This command performs data reconstruction only. It deliberately does not import
or invoke the frozen candidate evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_pitcher_k_historical_materializer import (
    FROZEN_SEASONS,
    HistoricalStatcastArchive,
    combine_seasons,
    fetch_season_schedule,
    materialize_season,
)


def _canonical_sha(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-days", type=int, default=45)
    args = parser.parse_args()

    source = MLBGenericHistorySource()
    season_results = []
    for season in FROZEN_SEASONS:
        schedule = fetch_season_schedule(season)
        archive = HistoricalStatcastArchive.fetch_season(season, chunk_days=args.chunk_days)
        season_results.append(
            materialize_season(
                season=season,
                source=source,
                archive=archive,
                schedule_payload=schedule,
            )
        )

    artifact = combine_seasons(season_results)
    artifact["materialization_sha256"] = _canonical_sha(artifact)
    artifact["evaluation_consumed"] = False
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(path),
        "row_count": artifact["row_count"],
        "season_receipts": artifact["season_receipts"],
        "materialization_sha256": artifact["materialization_sha256"],
        "evaluation_consumed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
