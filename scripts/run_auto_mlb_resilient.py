#!/usr/bin/env python3
"""Run SportsEdge MLB production card with report-aware Odds API key rotation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunnerError, report_to_dict, run_auto_mlb
from sportsedge.edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from sportsedge.live_odds_failover import should_rotate_odds_key

CHICAGO_TZ = ZoneInfo("America/Chicago")


def _keys_from_env() -> tuple[str, ...]:
    values = []
    for name in (
        "SPORTSEDGE_ODDS_API_KEY",
        "SPORTSEDGE_ODDS_API_KEY_2",
        "SPORTSEDGE_ODDS_API_KEY_3",
        "SPORTSEDGE_ODDS_API_KEY_4",
    ):
        value = os.environ.get(name, "").strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _prop_window_hours() -> float | None:
    raw = os.environ.get("SPORTSEDGE_ODDS_PROP_WINDOW_HOURS", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise AutoRunnerError("ODDS_PROP_WINDOW_INVALID") from exc
    if not math.isfinite(value) or value <= 0:
        raise AutoRunnerError("ODDS_PROP_WINDOW_INVALID")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="artifacts/live_mlb_card.json")
    p.add_argument("--require-confirmed-lineup", action="store_true")
    p.add_argument("--edge-floor-config", default=DEFAULT_EDGE_FLOOR_CONFIG)
    p.add_argument("--kelly-multiplier", type=float, default=0.25)
    args = p.parse_args()
    if args.edge_floor_config != DEFAULT_EDGE_FLOOR_CONFIG:
        p.error("production edge-floor config override is prohibited")

    quotes = os.environ.get("SPORTSEDGE_QUOTES_URL", "").strip()
    odds_api_keys = _keys_from_env()
    odds_books = tuple(
        x.strip() for x in os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings").split(",") if x.strip()
    )
    features = os.environ.get("SPORTSEDGE_FEATURES_URL", "").strip()
    projected = os.environ.get("SPORTSEDGE_PROJECTED_LINEUPS_URL", "").strip() or None
    token = os.environ.get("SPORTSEDGE_PROVIDER_TOKEN", "").strip() or None
    history_cache_dir = os.environ.get("SPORTSEDGE_HISTORY_CACHE_DIR", "").strip() or None
    prop_window_hours = _prop_window_hours()
    now = datetime.now(timezone.utc)

    infrastructure_blocked = False
    try:
        common = dict(
            projected_lineups_url=projected,
            provider_token=token,
            now=now,
            require_confirmed_lineup=args.require_confirmed_lineup,
            edge_floor_config_path=DEFAULT_EDGE_FLOOR_CONFIG,
            kelly_multiplier=args.kelly_multiplier,
        )
        if quotes:
            if not features:
                raise AutoRunnerError("FEATURE_PROVIDER_CONFIG_MISSING")
            report = run_auto_mlb(quote_url=quotes, feature_url=features, **common)
        elif odds_api_keys:
            attempts = []
            report = None
            for slot, key in enumerate(odds_api_keys, start=1):
                try:
                    candidate = run_auto_mlb_native_odds(
                        odds_api_key=key,
                        odds_api_keys=(),
                        feature_url=features or None,
                        bookmakers=odds_books,
                        history_cache_dir=history_cache_dir,
                        prop_window_hours=prop_window_hours,
                        **common,
                    )
                except Exception as exc:
                    attempts.append({
                        "key_slot": slot,
                        "rotated": True,
                        "reason": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                rotate = should_rotate_odds_key(
                    run_status=candidate.run_status,
                    results=candidate.results,
                    source_failures=candidate.source_failures,
                )
                attempts.append({"key_slot": slot, "rotated": bool(rotate)})
                if not rotate:
                    report = candidate
                    break
            if report is None:
                reasons = ";".join(
                    f"slot{x['key_slot']}={x.get('reason', 'NO_QUOTES')}" for x in attempts
                )
                raise AutoRunnerError("ODDS_API_NO_KEY_CAN_COVER_RUN:" + reasons)
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
    return 2 if infrastructure_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
