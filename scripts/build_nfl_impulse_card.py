#!/usr/bin/env python3
"""Build a user-directed NFL impulse card from SportsEdge run output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sportsedge.sports.nfl.impulse_mode import (
    ProfitBoostTerms,
    build_impulse_board,
    rank_profit_boost_sgps,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build NFL impulse card")
    parser.add_argument("input", type=Path, help="SportsEdge NFL run JSON")
    parser.add_argument("output", type=Path, help="output impulse card JSON")
    parser.add_argument("--team", action="append", default=[], help="team abbreviation; repeatable")
    parser.add_argument("--market", default=None)
    parser.add_argument("--min-model-p", type=float, default=0.0)
    parser.add_argument("--min-ev", type=float, default=0.0)
    parser.add_argument("--include-negative-ev", action="store_true")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--limit", type=int, default=None)

    parser.add_argument(
        "--promo-candidates",
        type=Path,
        default=None,
        help="optional JSON array of same-game parlay candidates with joint_model_probability",
    )
    parser.add_argument("--promo-wager", type=float, default=25.0)
    parser.add_argument("--promo-boost-rate", type=float, default=0.50)
    parser.add_argument("--promo-max-wager", type=float, default=25.0)
    parser.add_argument("--promo-min-legs", type=int, default=3)
    parser.add_argument("--promo-min-odds", type=int, default=-200)
    parser.add_argument("--promo-game", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.input.read_text())
    card = build_impulse_board(
        payload,
        teams=args.team,
        market=args.market,
        min_model_probability=args.min_model_p,
        min_ev=args.min_ev,
        include_negative_ev=args.include_negative_ev,
        include_stale=args.include_stale,
        limit=args.limit,
    )

    if args.promo_candidates is not None:
        candidates = json.loads(args.promo_candidates.read_text())
        if not isinstance(candidates, list):
            raise ValueError("promo candidates JSON must be an array")
        terms = ProfitBoostTerms(
            boost_rate=args.promo_boost_rate,
            max_wager=args.promo_max_wager,
            min_legs=args.promo_min_legs,
            min_total_american_odds=args.promo_min_odds,
            sgp_only=True,
            eligible_game=args.promo_game,
        )
        card["promo_sgps"] = rank_profit_boost_sgps(
            candidates,
            wager=args.promo_wager,
            terms=terms,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
