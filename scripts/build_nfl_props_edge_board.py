#!/usr/bin/env python3
"""Build a MySpariEdge-inspired NFL props board from SportsEdge run output.

The script is presentation-only.  It never creates Model_P, performs a second
simulation, devigs a market, or promotes a wager.  Those authorities remain in
the existing SportsEdge model/evidence pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sportsedge.sports.nfl.prop_edge_surface import (
    SUPPORTED_SORTS,
    SUPPORTED_VIEWS,
    build_props_edge_board,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the NFL props edge board")
    parser.add_argument("input", type=Path, help="governed football prop run JSON")
    parser.add_argument("output", type=Path, help="output board JSON")
    parser.add_argument(
        "--view",
        default="all_priced",
        choices=sorted(SUPPORTED_VIEWS),
        help="board view (featured is governed; research_featured is non-authoritative)",
    )
    parser.add_argument("--market", default=None, help="provider market or normalized stat")
    parser.add_argument("--team", action="append", default=[], help="team abbreviation; repeatable")
    parser.add_argument(
        "--sort",
        dest="sort_by",
        default="score",
        choices=sorted(SUPPORTED_SORTS),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--featured-min-score", type=float, default=0.0)
    parser.add_argument("--featured-min-edge", type=float, default=0.0)
    parser.add_argument("--featured-min-ev", type=float, default=0.0)
    parser.add_argument("--research-min-score", type=float, default=0.0)
    parser.add_argument("--research-min-edge", type=float, default=0.0)
    parser.add_argument("--research-min-ev", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.input.read_text())
    board = build_props_edge_board(
        payload,
        view=args.view,
        market=args.market,
        teams=args.team,
        sort_by=args.sort_by,
        limit=args.limit,
        featured_min_score=args.featured_min_score,
        featured_min_edge=args.featured_min_edge,
        featured_min_ev=args.featured_min_ev,
        research_min_score=args.research_min_score,
        research_min_edge=args.research_min_edge,
        research_min_ev=args.research_min_ev,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
