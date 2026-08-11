#!/usr/bin/env python3
"""Run SportsEdge's automated MLB card from configured live providers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunnerError, report_to_dict, run_auto_mlb

CHICAGO_TZ = ZoneInfo("America/Chicago")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="artifacts/live_mlb_card.json")
    p.add_argument("--require-confirmed-lineup", action="store_true")
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--kelly-multiplier", type=float, default=0.25)
    args = p.parse_args()
    quotes = os.environ.get("SPORTSEDGE_QUOTES_URL", "").strip()
    odds_api_keys = tuple(
        value for value in (
            os.environ.get("SPORTSEDGE_ODDS_API_KEY", "").strip(),
            os.environ.get("SPORTSEDGE_ODDS_API_KEY_2", "").strip(),
            os.environ.get("SPORTSEDGE_ODDS_API_KEY_3", "").strip(),
        ) if value
    )
    odds_books = tuple(x.strip() for x in os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings").split(",") if x.strip())
    features = os.environ.get("SPORTSEDGE_FEATURES_URL", "").strip()
    projected = os.environ.get("SPORTSEDGE_PROJECTED_LINEUPS_URL", "").strip() or None
    token = os.environ.get("SPORTSEDGE_PROVIDER_TOKEN", "").strip() or None
    history_cache_dir = os.environ.get("SPORTSEDGE_HISTORY_CACHE_DIR", "").strip() or None
    now = datetime.now(timezone.utc)
    infrastructure_blocked = False
    try:
        common = dict(
            projected_lineups_url=projected,
            provider_token=token,
            now=now,
            require_confirmed_lineup=args.require_confirmed_lineup,
            min_edge=args.min_edge,
            kelly_multiplier=args.kelly_multiplier,
        )
        if quotes:
            if not features:
                raise AutoRunnerError("FEATURE_PROVIDER_CONFIG_MISSING")
            report = run_auto_mlb(quote_url=quotes, feature_url=features, **common)
        elif odds_api_keys:
            report = run_auto_mlb_native_odds(
                odds_api_key=odds_api_keys[0],
                odds_api_keys=odds_api_keys[1:],
                feature_url=features or None,
                bookmakers=odds_books,
                history_cache_dir=history_cache_dir,
                **common,
            )
        else:
            raise AutoRunnerError("QUOTE_PROVIDER_CONFIG_MISSING")
        payload = report_to_dict(report)
    except Exception as exc:
        infrastructure_blocked = True
        payload = {
            "slate_date_ct": now.astimezone(CHICAGO_TZ).date().isoformat(),
            "generated_at_utc": now.isoformat(),
            "run_status": "BLOCKED",
            "results": [],
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
        }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    # A legitimate no-play card is success. Missing/broken infrastructure is not:
    # preserve the evidence artifact, but make automation visibly fail closed.
    return 2 if infrastructure_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
