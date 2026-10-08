#!/usr/bin/env python3
"""Run the unified NFL game + QB/RB/WR phone board.

The command discovers the upcoming schedule, pulls current PIT depth/injury
context and strictly-prior weekly player stats, then binds the already-pasted
two-sided prices after the model run.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sportsedge.nfl_unified_phone import build_unified_phone_card
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


def _fetch_season_source(fetcher, seasons: list[int]) -> list[dict]:
    """All-or-nothing source-family read with deterministic season ordering."""
    result: list[dict] = []
    for season in seasons:
        rows, _uri, _digest = fetcher(season=season)
        result.extend(rows)
    return result


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
            # Independent immutable nflverse source reads; preserve sorted season
            # order and wait for all providers before constructing the card.
            # Each provider fetches its own seasons serially, avoiding a burst
            # of concurrent requests against the same source family.
            stat_seasons = sorted({season for s in seasons for season in (s - 1, s)})
            with ThreadPoolExecutor(max_workers=3) as pool:
                depth_future = pool.submit(_fetch_season_source, fetch_nflverse_depth_charts, seasons)
                stats_future = pool.submit(fetch_nflverse_player_stats, seasons=stat_seasons)
                injury_future = pool.submit(_fetch_season_source, fetch_nflverse_injuries, seasons)
                # Do not pass partially acquired multi-season context to pricing.
                try:
                    depth_rows = depth_future.result()
                    source_status["depth"] = "AVAILABLE"
                except NFLContextError as exc:
                    depth_rows = []
                    source_status["depth"] = f"MISSING:{exc}"
                try:
                    player_rows, _receipts = stats_future.result()
                    source_status["player_stats"] = "AVAILABLE"
                except NFLContextError as exc:
                    player_rows = []
                    source_status["player_stats"] = f"MISSING:{exc}"
                try:
                    injury_rows = injury_future.result()
                    source_status["injuries"] = "AVAILABLE"
                    injury_source_ready = True
                except NFLContextError as exc:
                    injury_rows = []
                    source_status["injuries"] = f"MISSING:{exc}"

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
