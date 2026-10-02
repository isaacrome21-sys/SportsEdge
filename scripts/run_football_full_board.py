#!/usr/bin/env python3
"""Emit the football side, total, and prop presentation board.

Game and prop probabilities must already exist. Team totals can be derived only
from a supplied market-blind score distribution. Prop engine authority stays
NO_ENGINE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_full_board import build_football_full_board


def _load(path: Path | None) -> dict:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("FOOTBALL_FULL_BOARD_INPUT_INVALID")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=("NFL", "CFB"))
    parser.add_argument("--game-rows", type=Path)
    parser.add_argument("--prop-rows", type=Path)
    parser.add_argument("--team-total-requests", type=Path)
    parser.add_argument("--distribution", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    game = _load(args.game_rows).get("rows", [])
    props = _load(args.prop_rows).get("rows", [])
    requests = _load(args.team_total_requests).get("rows", [])
    distribution = _load(args.distribution).get("rows") if args.distribution else None
    board = build_football_full_board(
        sport=args.sport,
        game_rows=game,
        prop_rows=props,
        team_total_requests=requests,
        distribution=distribution,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(board["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
