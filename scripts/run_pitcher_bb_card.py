#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.card_io import normalize_feature_rows, normalize_quotes
from sportsedge.feature_plan import resolve_feature_plan
from sportsedge.live_capture import capture_slate
from sportsedge.pitcher_card_pipeline import run_pitcher_bb_card, pitcher_card_result_to_dict
from sportsedge.quote_bridge import normalize_offer_snapshot


def _load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Capture MLB probable starters and run validated pitcher-walk card pipeline")
    p.add_argument("--date", required=True)
    fg = p.add_mutually_exclusive_group(required=True)
    fg.add_argument("--features")
    fg.add_argument("--feature-plan")
    p.add_argument("--sources")
    qg = p.add_mutually_exclusive_group(required=True)
    qg.add_argument("--quotes")
    qg.add_argument("--offer-snapshot")
    p.add_argument("--quote-ttl-seconds", type=int, default=300)
    p.add_argument("--registry", default="config/deployments.json")
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--kelly-multiplier", type=float, default=0.25)
    args = p.parse_args()

    ingestion_now = datetime.now(timezone.utc)
    feature_failures = []
    if args.features:
        features = normalize_feature_rows(_load(args.features))
    else:
        if not args.sources:
            p.error("--sources is required with --feature-plan")
        features, feature_failures = resolve_feature_plan(_load(args.feature_plan), sources=_load(args.sources), now=ingestion_now)

    quote_failures = []
    if args.quotes:
        quotes = normalize_quotes(_load(args.quotes))
    else:
        quotes, quote_failures = normalize_offer_snapshot(_load(args.offer_snapshot), default_ttl_seconds=args.quote_ttl_seconds)

    captures = capture_slate(args.date)
    games = [x.live_game for x in captures if x.live_game is not None]
    finalization_now = datetime.now(timezone.utc)
    card = run_pitcher_bb_card(
        games=games, feature_rows=features, quotes=quotes,
        ingestion_now=ingestion_now, finalization_now=finalization_now,
        registry_path=args.registry, min_edge=args.min_edge,
        kelly_multiplier=args.kelly_multiplier,
    )
    payload = {
        "date": args.date,
        "feature_resolution": {"resolved": len(features), "blocked": len(feature_failures), "failures": feature_failures},
        "quote_resolution": {"resolved": len(quotes), "blocked": len(quote_failures), "failures": quote_failures},
        "card": [pitcher_card_result_to_dict(x) for x in card],
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
