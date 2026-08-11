#!/usr/bin/env python3
"""Run SportsEdge's automated MLB card from configured live providers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sportsedge.auto_runner import AutoRunnerError, report_to_dict, run_auto_mlb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="artifacts/live_mlb_card.json")
    p.add_argument("--require-confirmed-lineup", action="store_true")
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--kelly-multiplier", type=float, default=0.25)
    args = p.parse_args()
    quotes = os.environ.get("SPORTSEDGE_QUOTES_URL", "").strip()
    features = os.environ.get("SPORTSEDGE_FEATURES_URL", "").strip()
    projected = os.environ.get("SPORTSEDGE_PROJECTED_LINEUPS_URL", "").strip() or None
    token = os.environ.get("SPORTSEDGE_PROVIDER_TOKEN", "").strip() or None
    now = datetime.now(timezone.utc)
    try:
        if not quotes or not features:
            raise AutoRunnerError("PROVIDER_CONFIG_MISSING")
        report = run_auto_mlb(quote_url=quotes, feature_url=features, projected_lineups_url=projected, provider_token=token, now=now, require_confirmed_lineup=args.require_confirmed_lineup, min_edge=args.min_edge, kelly_multiplier=args.kelly_multiplier)
        payload = report_to_dict(report)
    except Exception as exc:
        payload = {"slate_date_ct": now.astimezone().date().isoformat(), "generated_at_utc": now.isoformat(), "run_status": "BLOCKED", "results": [], "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}]}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
