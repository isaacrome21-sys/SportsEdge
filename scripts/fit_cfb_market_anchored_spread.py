#!/usr/bin/env python3
"""Fit the frozen CFB spread anchor from trusted cached development history."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import backtest_cfb_sdv_vs_lines as bt
from sportsedge.sports.cfb import cfbd_issue_cache
from sportsedge.sports.cfb.market_anchored_spread import fit_market_anchored_spread


def cached_lines(seasons, cache):
    out = {}
    missing = []
    for season in seasons:
        key = f"lines_{int(season)}"
        rows = cache.get(key)
        if not isinstance(rows, dict) or not rows:
            missing.append(key)
        else:
            out.update(rows)
    if missing:
        raise SystemExit("CFB_ANCHORED_SPREAD_CACHE_MISSING:" + ",".join(missing))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", help="Optional local SDV training_rows.json; otherwise data branch")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)

    rows = bt.load_rows(args.rows)
    predictions = bt.loso_predictions(rows)
    seasons = sorted({int(row["season"]) for row in predictions.values()})
    if seasons != list(range(2016, 2026)):
        raise SystemExit("CFB_ANCHORED_SPREAD_SEASON_SET_MISMATCH:" + ",".join(map(str, seasons)))
    cache = cfbd_issue_cache.load_cache(issue=1475)
    lines = cached_lines(seasons, cache)
    fit = fit_market_anchored_spread(predictions, lines)
    payload = fit.to_dict()
    payload.update({
        "tracking_issue": 1602,
        "cache_issue": 1475,
        "prediction_family": "PRIOR_CURRENT_BLEND",
        "prediction_method": "LEAVE_ONE_SEASON_OUT",
        "line_role": "CACHED_DEVELOPMENT_CLOSE_REFERENCE",
        "totals_enabled": False,
        "no_backfill": True,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CFB_MARKET_ANCHORED_SPREAD_FIT")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
