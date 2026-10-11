#!/usr/bin/env python3
"""Run the unified NFL game + QB/RB/WR phone board.

The command discovers the upcoming schedule, pulls current PIT depth/injury
context and strictly-prior weekly player stats, then binds the already-pasted
two-sided prices after the model run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone, date

from sportsedge.nfl_unified_phone import build_unified_phone_card
from sportsedge.nfl_attempt9_live_forecast import (
    load_runtime, raw_forecasts, recency_features,
)
from sportsedge.sports.nfl.market_residual_research import (
    NFLResidualError, price_game_from_pairs,
)
from scripts.run_nfl_lines_card import _history_rows
from sportsedge.nfl_scoring_composition_artifact import load_prior_file
from sportsedge.sports.nfl.auto_slate import discover_nfl_auto_games
from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.full_auto import fetch_nflverse_depth_charts
from sportsedge.sports.nfl.injury_report_source import fetch_nflverse_injuries
from sportsedge.sports.nfl.live_role_source import fetch_nflverse_player_stats


def _read(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _has_props(ticket: dict) -> bool:
    return any(
        str(row.get("player") or "").strip()
        for game in ticket.get("games") or []
        for row in game.get("markets") or []
        if isinstance(row, dict)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-sims", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--horizon-days", type=int, default=10)
    ap.add_argument("--scoring-prior")
    args = ap.parse_args()

    ticket = _read(args.input)
    history = _read(args.history)
    observed_at = ticket.get("observed_at")
    if not observed_at:
        raise SystemExit("NFL_UNIFIED_PHONE_OBSERVED_AT_REQUIRED")

    plan = discover_nfl_auto_games(
        as_of=observed_at,
        min_lead_minutes=0,
        horizon_minutes=max(1, int(args.horizon_days)) * 24 * 60,
        game_types=("REG", "POST"),
    )
    schedule_games = list(plan.get("games") or [])
    seasons = sorted({
        int(row["season"])
        for row in schedule_games
        if row.get("season") not in (None, "")
    })

    depth_rows = []
    player_rows = []
    injury_rows = []
    source_status = {
        "schedule": "AVAILABLE",
        "depth": "NOT_REQUIRED",
        "player_stats": "NOT_REQUIRED",
        "injuries": "NOT_REQUIRED",
    }
    injury_source_ready = False

    if _has_props(ticket):
        if not seasons:
            source_status["depth"] = "MISSING:NO_SCHEDULE_SEASON"
            source_status["player_stats"] = "MISSING:NO_SCHEDULE_SEASON"
            source_status["injuries"] = "MISSING:NO_SCHEDULE_SEASON"
        else:
            for season in seasons:
                try:
                    rows, _uri, _digest = fetch_nflverse_depth_charts(season=season)
                    depth_rows.extend(rows)
                    source_status["depth"] = "AVAILABLE"
                except NFLContextError as exc:
                    source_status["depth"] = f"MISSING:{exc}"

            stat_seasons = sorted({season for s in seasons for season in (s - 1, s)})
            try:
                player_rows, _receipts = fetch_nflverse_player_stats(seasons=stat_seasons)
                source_status["player_stats"] = "AVAILABLE"
            except NFLContextError as exc:
                source_status["player_stats"] = f"MISSING:{exc}"

            injury_ok = True
            for season in seasons:
                try:
                    rows, _uri, _digest = fetch_nflverse_injuries(season=season)
                    injury_rows.extend(rows)
                except NFLContextError as exc:
                    injury_ok = False
                    source_status["injuries"] = f"MISSING:{exc}"
            if injury_ok:
                source_status["injuries"] = "AVAILABLE"
                injury_source_ready = True

    scoring_prior = load_prior_file(args.scoring_prior) if args.scoring_prior else None

    payload = build_unified_phone_card(
        ticket,
        history=history,
        schedule_games=schedule_games,
        depth_rows=depth_rows,
        player_rows=player_rows,
        injury_rows=injury_rows,
        injury_source_ready=injury_source_ready,
        scoring_prior=scoring_prior,
        n_sims=int(args.n_sims),
        seed=int(args.seed),
    )
    # Only add an independent game-price research sidecar. The pinned unified
    # player-role/scoring implementation stays byte-identical and its disabled
    # game-market authority is NOT changed.
    historical = _history_rows(history)
    raw_runtime = load_runtime()
    residual_games = []
    now = datetime.now(timezone.utc)
    for index, source_game in enumerate(ticket.get("games") or []):
        result = {"status":"NO_MODEL", "reason":"RESIDUAL_INDEPENDENT_MODEL_UNAVAILABLE"}
        try:
            schedule_game = payload["games"][index]
            kickoff = datetime.fromisoformat(
                str(schedule_game["kickoff"]).replace("Z","+00:00"))
            if kickoff.tzinfo is None:
                raise NFLResidualError("KICKOFF_TIMEZONE_MISSING")
            features = recency_features(
                historical,home=str(source_game["home"]),away=str(source_game["away"]),
                asof=kickoff.date(),
            )
            if not features.get("ok"):
                raise NFLResidualError(str(features.get("reason")))
            independent = raw_forecasts(raw_runtime,features["vector"])
            priced = price_game_from_pairs(
                raw_margin=independent["margin"],raw_total=independent["total"],
                markets=source_game.get("markets") or [],
                observed_at=ticket.get("observed_at"),
                as_of=now,kickoff_at=kickoff,
                model_family="ATTEMPT9_RAW_UNIFIED_SIDECAR",
            )
            result = {"status":"RESEARCH_ONLY","research":priced}
        except (NFLResidualError,ValueError,TypeError,KeyError,IndexError) as exc:
            result = {"status":"NO_MODEL","reason":str(exc)[:180]}
        residual_games.append(result)
        if index < len(payload.get("games") or []):
            payload["games"][index]["residual_pricing"] = result
    payload["residual_research_games"] = residual_games
    payload["residual_pricing_authority"] = {
        "research_only":True,"model_p":False,
        "official":False,"promotion":False,"staking":False,
    }
    payload["source_status"] = source_status
    payload["schedule_source_sha256"] = plan.get("schedule_source_sha256")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "games": len(payload.get("games") or []),
        "rows": len(payload.get("rows") or []),
        "selected_rows": len(payload.get("selected_rows") or []),
        "source_status": source_status,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
