#!/usr/bin/env python3
"""Build a fail-closed NFL experimental research card.

The input JSON must carry the current forecast/input fingerprints and timestamped
book offers. The command refuses to manufacture freshness or betting authority.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sportsedge.sports.nfl.research_card import build_nfl_research_card


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build NFL EXPERIMENTAL / NOT OFFICIAL card")
    parser.add_argument("input", type=Path, help="research-card input JSON")
    parser.add_argument("output", type=Path, help="research-card output JSON")
    parser.add_argument(
        "--max-quote-age-seconds",
        type=float,
        default=900.0,
        help="maximum publishable quote age; default 900 seconds",
    )
    parser.add_argument("--min-ev", type=float, default=0.0)
    parser.add_argument("--min-probability-edge", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.input.read_text())
    card = build_nfl_research_card(
        game_market_rows=payload.get("game_market_rows") or [],
        prop_run_payload=payload.get("prop_run_payload"),
        forecast_provenance=payload.get("forecast_provenance") or {},
        current_input_fingerprint=payload.get("current_input_fingerprint") or "",
        current_input_as_of=payload.get("current_input_as_of"),
        as_of=payload.get("as_of"),
        max_quote_age_seconds=args.max_quote_age_seconds,
        min_ev=args.min_ev,
        min_probability_edge=args.min_probability_edge,
        roster_team_by_player_id=payload.get("roster_team_by_player_id"),
        splits_context=payload.get("splits_context"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
