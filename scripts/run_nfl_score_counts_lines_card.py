#!/usr/bin/env python3
"""Run NFL_SCORE_COUNTS_G1 full game + player phone board.

The score-count prediction must already exist before the sportsbook board's
observed_at timestamp. Quotes are bound only after that frozen distribution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.nfl_score_counts_phone import build_score_count_phone_card
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


def _game_only_ticket(ticket: dict) -> dict:
    out = dict(ticket)
    games = []
    for raw_game in ticket.get("games") or []:
        if not isinstance(raw_game, dict):
            continue
        game = dict(raw_game)
        game["markets"] = [
            dict(row)
            for row in raw_game.get("markets") or []
            if isinstance(row, dict) and not str(row.get("player") or "").strip()
        ]
        games.append(game)
    out["games"] = games
    return out


def _write_payload(path: str | Path, payload: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--prediction", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--fast-game-output")
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--horizon-days", type=int, default=10)
    ap.add_argument("--scoring-prior")
    args = ap.parse_args()

    ticket = _read(args.input)
    prediction = _read(args.prediction)
    observed_at = ticket.get("observed_at")
    if not observed_at:
        raise SystemExit("NFL_SCORE_COUNTS_PHONE_OBSERVED_AT_REQUIRED")

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

    if args.fast_game_output:
        fast_payload = build_score_count_phone_card(
            _game_only_ticket(ticket),
            prediction=prediction,
            schedule_games=schedule_games,
            depth_rows=(),
            player_rows=(),
            injury_rows=(),
            injury_source_ready=False,
            scoring_prior=None,
            seed=int(args.seed),
        )
        fast_payload["source_status"] = {
            "schedule": "AVAILABLE",
            "depth": "NOT_REQUIRED_FOR_GAME_MARKETS",
            "player_stats": "NOT_REQUIRED_FOR_GAME_MARKETS",
            "injuries": "NOT_REQUIRED_FOR_GAME_MARKETS",
        }
        fast_payload["schedule_source_sha256"] = plan.get("schedule_source_sha256")
        fast_payload["fast_game_markets_only"] = True
        _write_payload(args.fast_game_output, fast_payload)

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
    payload = build_score_count_phone_card(
        ticket,
        prediction=prediction,
        schedule_games=schedule_games,
        depth_rows=depth_rows,
        player_rows=player_rows,
        injury_rows=injury_rows,
        injury_source_ready=injury_source_ready,
        scoring_prior=scoring_prior,
        seed=int(args.seed),
    )
    payload["source_status"] = source_status
    payload["schedule_source_sha256"] = plan.get("schedule_source_sha256")

    _write_payload(args.output, payload)
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
