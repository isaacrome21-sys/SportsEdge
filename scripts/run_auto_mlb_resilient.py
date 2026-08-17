#!/usr/bin/env python3
"""Run SportsEdge MLB card with paid-key rotation and ESPN game-market fallback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.auto_espn_odds import run_auto_mlb_espn_game_odds
from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunnerError, report_to_dict, run_auto_mlb
from sportsedge.edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from sportsedge.funnel import build_funnel
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
        else:
            attempts = []
            report = None
            for slot, key in enumerate(odds_api_keys, start=1):
                candidate = run_auto_mlb_native_odds(
                    odds_api_key=key,
                    odds_api_keys=(),
                    feature_url=features or None,
                    bookmakers=odds_books,
                    history_cache_dir=history_cache_dir,
                    **common,
                )
                rotate = should_rotate_odds_key(
                    run_status=candidate.run_status,
                    results=candidate.results,
                    source_failures=candidate.source_failures,
                )
                attempts.append({"key_slot": slot, "rotated": bool(rotate)})
                if not rotate:
                    report = candidate
                    break

            # The Odds API may be exhausted or entirely unconfigured. Preserve
            # full-game ML/RL/totals via ESPN's no-key scoreboard odds instead
            # of turning the whole card into BLOCKED_NO_ODDS. Player props stay
            # fail-closed and are explicitly reported as unavailable on this lane.
            if report is None:
                report = run_auto_mlb_espn_game_odds(
                    feature_url=features or None,
                    history_cache_dir=history_cache_dir,
                    **common,
                )

        payload = report_to_dict(report)
        game_ids = {
            str(item.game_id) for item in report.results
            if str(item.game_id).isdigit() and int(str(item.game_id)) > 0
        }
        feature_built = sum(item.model_p is not None for item in report.results)
        lineup_block_tokens = ("LINEUP", "PROJECTED_LINEUP")
        lineup_blocked_games = {
            str(item.game_id) for item in report.results
            if any(token in str(item.reason).upper() for token in lineup_block_tokens)
        }
        funnel = build_funnel(
            results=report.results,
            source_failures=report.source_failures,
            games_scheduled=len(game_ids) if game_ids else None,
            lineups_confirmed=max(0, len(game_ids) - len(lineup_blocked_games)) if game_ids else None,
            features_built=feature_built,
        )
        payload["funnel"] = funnel

        # A valid no-edge/no-bet slate is success. Zero sportsbook rows is not.
        if funnel["odds_rows_fetched"] == 0:
            infrastructure_blocked = True
            payload["run_status"] = "BLOCKED_NO_ODDS"
            payload.setdefault("source_failures", []).append({
                "stage": "FUNNEL",
                "reason": "NO_ODDS_ROWS_REACHED_PRICING",
            })
    except Exception as exc:
        infrastructure_blocked = True
        payload = {
            "slate_date_ct": now.astimezone(CHICAGO_TZ).date().isoformat(),
            "generated_at_utc": now.isoformat(),
            "run_status": "BLOCKED",
            "results": [],
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
            "funnel": {
                "games_scheduled": None,
                "odds_rows_fetched": 0,
                "lineups_confirmed": None,
                "features_built": 0,
                "model_priced": 0,
                "edge_positive": 0,
                "shadow_bets": 0,
                "bets_emitted": 0,
                "blocked_rows": 0,
                "pipeline_health": "BROKEN",
                "pipeline_health_reason": "RUNNER_EXCEPTION",
                "gate_kill_counts": {f"{type(exc).__name__}: {exc}": 1},
                "edge_distribution": [],
            },
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if infrastructure_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
