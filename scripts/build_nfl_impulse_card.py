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
from sportsedge.sports.nfl.player_path_overlay_v1 import (
    simulate_player_overlays_by_seed,
)
from sportsedge.sports.nfl.sgp_joint_probability import (
    enrich_sgp_candidates_with_joint_probability,
)
from sportsedge.sports.nfl.sgp_v2k_adapter import attach_player_stats_by_seed


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
        help="optional JSON array of same-game parlay candidates",
    )
    parser.add_argument(
        "--simulation-paths",
        type=Path,
        default=None,
        help="optional JSON array of same-game simulation paths used to compute candidate joint P",
    )
    parser.add_argument(
        "--player-path-profiles",
        type=Path,
        default=None,
        help="optional football-only team/player profiles used to add same-seed player outcomes to simulation paths",
    )
    parser.add_argument(
        "--player-path-seed-salt",
        type=int,
        default=9102026,
        help="deterministic RNG salt for same-seed player outcome overlays",
    )
    parser.add_argument(
        "--allow-partial-simulation-paths",
        action="store_true",
        help="allow paths with missing leg data to be excluded instead of failing closed",
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

    if args.player_path_profiles is not None and args.simulation_paths is None:
        raise ValueError("--player-path-profiles requires --simulation-paths")

    if args.promo_candidates is not None:
        candidates = json.loads(args.promo_candidates.read_text())
        if not isinstance(candidates, list):
            raise ValueError("promo candidates JSON must be an array")

        joint_source = "CANDIDATE_PAYLOAD"
        if args.simulation_paths is not None:
            simulation_paths = json.loads(args.simulation_paths.read_text())
            if not isinstance(simulation_paths, list):
                raise ValueError("simulation paths JSON must be an array")

            if args.player_path_profiles is not None:
                profiles = json.loads(args.player_path_profiles.read_text())
                if not isinstance(profiles, dict):
                    raise ValueError("player path profiles JSON must be an object keyed by team")
                overlays = simulate_player_overlays_by_seed(
                    simulation_paths,
                    profiles,
                    seed_salt=args.player_path_seed_salt,
                )
                simulation_paths = attach_player_stats_by_seed(
                    simulation_paths,
                    overlays,
                    strict=not args.allow_partial_simulation_paths,
                )
                joint_source = "SAME_SIMULATION_PATHS_WITH_PLAYER_OVERLAY_V1"
            else:
                joint_source = "SAME_SIMULATION_PATHS"

            candidates = enrich_sgp_candidates_with_joint_probability(
                candidates,
                simulation_paths,
                strict=not args.allow_partial_simulation_paths,
            )

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
        card["promo_joint_probability_source"] = joint_source

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
