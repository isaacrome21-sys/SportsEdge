#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.card_io import normalize_feature_rows, normalize_quotes
from sportsedge.card_pipeline import run_hitter_card, card_result_to_dict
from sportsedge.feature_plan import resolve_feature_plan
from sportsedge.live_capture import capture_slate


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Capture MLB lineups and run the validated hitter-card pipeline")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    feature_group = p.add_mutually_exclusive_group(required=True)
    feature_group.add_argument("--features", help="JSON list of already-resolved market-specific feature rows")
    feature_group.add_argument("--feature-plan", help="JSON list of feature targets resolved from timestamped source facts")
    p.add_argument("--sources", help="JSON list of timestamped source facts; required with --feature-plan")
    p.add_argument("--quotes", required=True, help="JSON list of canonical sportsbook quotes")
    p.add_argument("--registry", default="config/deployments.json")
    p.add_argument("--allow-projected-lineups", action="store_true")
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--kelly-multiplier", type=float, default=0.25)
    args = p.parse_args()

    ingestion_now = datetime.now(timezone.utc)
    feature_failures = []
    if args.features:
        features = normalize_feature_rows(_load_json(args.features))
    else:
        if not args.sources:
            p.error("--sources is required with --feature-plan")
        features, feature_failures = resolve_feature_plan(
            _load_json(args.feature_plan),
            sources=_load_json(args.sources),
            now=ingestion_now,
        )

    quotes = normalize_quotes(_load_json(args.quotes))
    captures = capture_slate(args.date)
    games = [x.live_game for x in captures if x.live_game is not None]
    finalization_now = datetime.now(timezone.utc)

    card = run_hitter_card(
        games=games,
        feature_rows=features,
        quotes=quotes,
        ingestion_now=ingestion_now,
        finalization_now=finalization_now,
        registry_path=args.registry,
        require_confirmed_lineup=not args.allow_projected_lineups,
        min_edge=args.min_edge,
        kelly_multiplier=args.kelly_multiplier,
    )
    payload = {
        "date": args.date,
        "ingestion_now": ingestion_now.isoformat(),
        "finalization_now": finalization_now.isoformat(),
        "capture": {
            "games": len(captures),
            "confirmed_games": sum(x.status == "LINEUPS_CONFIRMED" for x in captures),
            "partial_games": sum(x.status == "LINEUPS_PARTIAL" for x in captures),
            "capture_blocked": sum(x.status == "CAPTURE_BLOCKED" for x in captures),
        },
        "feature_resolution": {
            "resolved": len(features),
            "blocked": len(feature_failures),
            "failures": feature_failures,
        },
        "card": [card_result_to_dict(x) for x in card],
        "counts": {
            "official_bets": sum(x.bet_status == "OFFICIAL_BET" for x in card),
            "passes": sum(x.bet_status == "PASS" for x in card),
            "blocked": sum(x.bet_status == "BLOCKED" for x in card),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
