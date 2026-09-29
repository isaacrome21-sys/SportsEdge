#!/usr/bin/env python3
from __future__ import annotations

"""Fit the SportsEdge NHL public-boxscore development baseline artifact."""

import argparse
import json
from pathlib import Path
import sys

from sportsedge.sports.nhl.official_boxscore_source import (
    completed_game_from_json_dict,
    dataset_sha256,
)
from sportsedge.sports.nhl.public_baseline import (
    build_baseline_training_rows,
    fit_public_baseline,
)


def _load_games(path: Path):
    games = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            game = completed_game_from_json_dict(json.loads(line))
        except Exception as exc:
            raise ValueError(f"invalid input JSONL row {line_number}: {exc}") from exc
        if game.game_id in seen:
            raise ValueError(f"duplicate input game id:{game.game_id}")
        seen.add(game.game_id)
        games.append(game)
    if not games:
        raise ValueError("input contains no completed games")
    return games


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit market-blind NHL public-boxscore baseline")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ridge", type=float, default=1.0)
    parser.add_argument("--min-team-games", type=int, default=10)
    parser.add_argument("--game-type", action="append", type=int, dest="game_types", help="Allowed NHL game type; repeatable (default: 2,3)")
    args = parser.parse_args()

    games = _load_games(args.input)
    allowed = tuple(args.game_types or (2, 3))
    rows = build_baseline_training_rows(
        games, min_team_games=args.min_team_games, allowed_game_types=allowed,
    )
    artifact = fit_public_baseline(rows, version=args.version, ridge=args.ridge)
    payload = {
        "schema": "sportsedge.nhl.public_boxscore_baseline.v1",
        "source_dataset_sha256": dataset_sha256(games),
        "source_games": len(games),
        "allowed_game_types": list(allowed),
        "min_team_games": args.min_team_games,
        "artifact": artifact.as_json_dict(),
        "authority": "DEVELOPMENT_BASELINE / NOT Model_P / NOT TRUTH_GATE / NOT OFFICIAL",
        "evidence_note": (
            "Historical receipts are valid development inputs from their actual retrieval time. "
            "This artifact does not create retroactive PIT betting evidence; promotion requires forward validation."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"games={len(games)} training_rows={len(rows)} training_sha256={artifact.training_sha256} output={args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
