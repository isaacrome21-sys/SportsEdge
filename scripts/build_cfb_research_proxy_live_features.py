#!/usr/bin/env python3
"""Build automatic same-day CFB research-proxy live features.

This path is for LEAN/research output only.  It fetches current CFBD schedule,
team identity and player usage before player-prop prices are acquired.  Missing
snap/route/red-zone/injury dimensions remain explicit neutral assumptions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_cfb_auto import discover_cfb_week
from sportsedge.sports.cfb.prop_bundle import load_cfb_prop_artifact_bundle
from sportsedge.sports.cfb.research_proxy_usage import (
    CFBResearchProxyUsageError,
    build_research_proxy_live_features,
    fetch_cfbd_player_usage,
    fetch_odds_event_identities,
)
from sportsedge.sports.cfb.source import fetch_cfbd_games, fetch_cfbd_teams


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    out = datetime.fromisoformat(raw)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("CFB_PROXY_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _credentials() -> tuple[str, list[str]]:
    cfbd = str(
        os.environ.get("SPORTSEDGE_CFBD_API_KEY")
        or os.environ.get("CFBD_API_KEY")
        or ""
    ).strip()
    odds_keys = [
        str(os.environ.get(name) or "").strip()
        for name in (
            "SPORTSEDGE_ODDS_API_KEY",
            "SPORTSEDGE_ODDS_API_KEY_2",
            "SPORTSEDGE_ODDS_API_KEY_3",
            "SPORTSEDGE_ODDS_API_KEY_4",
            "ODDS_API_KEY",
        )
    ]
    odds_keys = list(dict.fromkeys(key for key in odds_keys if key))
    if not cfbd:
        raise CFBResearchProxyUsageError("CFB_PROXY_CFBD_API_KEY_REQUIRED")
    if not odds_keys:
        raise CFBResearchProxyUsageError("CFB_PROXY_ODDS_API_KEY_REQUIRED")
    return cfbd, odds_keys


def _allowed_model_teams(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    try:
        payload = load_cfb_prop_artifact_bundle(
            root=ROOT,
            bundle_path=path,
        )
    except Exception as exc:
        raise CFBResearchProxyUsageError(
            "CFB_PROXY_MODEL_ARTIFACT_UNREADABLE"
        ) from exc
    profiles = payload.get("team_drive_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise CFBResearchProxyUsageError(
            "CFB_PROXY_MODEL_TEAM_PROFILES_REQUIRED"
        )
    return {str(team) for team in profiles}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--asof")
    ap.add_argument("--horizon-hours", type=float, default=24.0)
    ap.add_argument(
        "--model-artifact",
        type=Path,
        default=ROOT / "artifacts/football/cfb_prop_artifact_bundle_v1.json",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/football/cfb_prop_proxy_live_features.json",
    )
    args = ap.parse_args()
    now = _utc(args.asof)
    try:
        cfbd_key, odds_keys = _credentials()
        season = int(args.season if args.season is not None else now.year)
        week = int(args.week) if args.week is not None else discover_cfb_week(
            season=season,
            now=now,
            cfbd_api_key=cfbd_key,
        )
        # Market-blind football state first.
        team_rows = fetch_cfbd_teams(
            season=season, cfbd_api_key=cfbd_key
        )
        games = fetch_cfbd_games(
            season=season, week=week, cfbd_api_key=cfbd_key
        )
        usage = fetch_cfbd_player_usage(
            season=season, cfbd_api_key=cfbd_key
        )
        # Provider identity only: event id/name/start, never price or line.
        provider_events = fetch_odds_event_identities(api_keys=odds_keys)
        live = build_research_proxy_live_features(
            games=games,
            team_rows=team_rows,
            player_usage_rows=usage,
            provider_events=provider_events,
            season=season,
            now=now,
            horizon_hours=float(args.horizon_hours),
            allowed_model_teams=_allowed_model_teams(args.model_artifact),
        )
        live["season"] = season
        live["week"] = week
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(live, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "status": "SUCCESS",
            "season": season,
            "week": week,
            "games": len(live["games"]),
            "blocked_games": len(live["blocked_games"]),
            "research_proxy_usage": True,
            "production_eligible": False,
            "official_eligible": False,
            "output": str(args.output),
        }, sort_keys=True))
        return 0
    except Exception as exc:
        payload = {
            "status": "BLOCKED",
            "blocker": f"{type(exc).__name__}:{exc}",
            "research_proxy_usage": True,
            "production_eligible": False,
            "official_eligible": False,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
