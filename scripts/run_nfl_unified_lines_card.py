#!/usr/bin/env python3
"""Run the unified NFL game + QB/RB/WR phone board.

The command discovers the upcoming schedule, pulls current PIT depth/injury
context and strictly-prior weekly player stats, then binds the already-pasted
two-sided prices after the model run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
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


_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
def _name_tokens(value) -> list[str]:
    text = str(value or "").casefold()
    for mark in (".", ",", "-", "'", "’"):
        text = text.replace(mark, " ")
    tokens = text.split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return tokens


def _name_alias_match(left, right) -> bool:
    a = _name_tokens(left)
    b = _name_tokens(right)
    if a == b:
        return True
    if len(a) >= 2 and len(b) >= 2 and a[-1] == b[-1]:
        first_a, first_b = a[0], b[0]
        return min(len(first_a), len(first_b)) >= 4 and (
            first_a.startswith(first_b) or first_b.startswith(first_a)
        )
    return False


def _normalize_ticket_prop_players(ticket: dict, depth_rows: list[dict]) -> tuple[dict, list[dict]]:
    """Bind narrow sportsbook/depth-chart name aliases before the frozen V1 card."""
    normalized = deepcopy(ticket)
    bindings: list[dict] = []
    for game in normalized.get("games") or []:
        away = str(game.get("away") or "").strip().upper()
        home = str(game.get("home") or "").strip().upper()
        teams = {away, home}
        candidates = sorted({
            (
                str(row.get("team") or row.get("club_code") or "").strip().upper(),
                str(row.get("player_name") or "").strip(),
            )
            for row in depth_rows
            if str(row.get("team") or row.get("club_code") or "").strip().upper() in teams
            and str(row.get("player_name") or "").strip()
        })
        for raw in game.get("markets") or []:
            if not isinstance(raw, dict):
                continue
            player = str(raw.get("player") or "").strip()
            if not player:
                continue
            hits = [(team, name) for team, name in candidates if _name_alias_match(name, player)]
            if len(hits) != 1:
                continue
            team, canonical = hits[0]
            raw["player"] = canonical
            raw["team"] = team
            if canonical != player:
                bindings.append({
                    "game": f"{away}@{home}",
                    "input": player,
                    "canonical": canonical,
                    "team": team,
                })
    return normalized, bindings


def _apply_prop_board_safety(payload: dict, ticket: dict) -> dict:
    """Presentation/serving guard: never emit a mechanically one-sided prop card."""
    out = deepcopy(payload)
    games = out.get("games") or []
    ticket_games = ticket.get("games") or []
    for game_index, game in enumerate(games):
        if game_index >= len(ticket_games):
            continue
        raw_game = ticket_games[game_index]
        away = str(raw_game.get("away") or "").strip().upper()
        home = str(raw_game.get("home") or "").strip().upper()
        rows = game.get("rows") or []
        prop_indexes_by_team: dict[str, set[int]] = {}
        all_prop_indexes: set[int] = set()
        for input_index, raw in enumerate(raw_game.get("markets") or []):
            if not isinstance(raw, dict) or not str(raw.get("player") or "").strip():
                continue
            all_prop_indexes.add(input_index)
            team = str(raw.get("team") or "").strip().upper()
            if team not in {away, home}:
                engine_sides = {
                    str(row.get("team") or "").strip().lower()
                    for row in rows
                    if int(row.get("input_index", -1)) == input_index
                    and str(row.get("team") or "").strip().lower() in {"home", "away"}
                }
                if engine_sides == {"home"}:
                    team = home
                elif engine_sides == {"away"}:
                    team = away
            if team in {away, home}:
                prop_indexes_by_team.setdefault(team, set()).add(input_index)

        failed_teams: list[str] = []
        if len(prop_indexes_by_team) >= 2:
            for team, indexes in sorted(prop_indexes_by_team.items()):
                team_rows = [
                    row for row in rows
                    if int(row.get("input_index", -1)) in indexes
                ]
                if not any(row.get("status") == "PRICED" for row in team_rows):
                    failed_teams.append(team)

        engine = game.setdefault("engine", {})
        if failed_teams:
            detail = ",".join(failed_teams)
            reason = f"GAME_PROP_SIMULATION_INCOMPLETE:{detail}=NO_PRICED_PROP_ROWS"
            for row in rows:
                if int(row.get("input_index", -1)) not in all_prop_indexes:
                    continue
                row["status"] = "NO_MODEL"
                row["reason"] = reason
                row["selected"] = False
                row["card_eligible"] = False
                row["card_reason"] = reason
                for key in (
                    "estimate_p", "push_p", "loss_p", "conditional_win_probability",
                    "fair_american", "edge_probability_points", "ev_per_dollar",
                    "score_0_100", "score_label",
                ):
                    row.pop(key, None)
            engine["prop_board_status"] = "NO_MODEL"
            engine["prop_board_error"] = reason
            engine["failed_requested_teams"] = failed_teams
            game["role_status"] = "NO_MODEL"
            game["role_error"] = reason
            game["status"] = "NO_MODEL_PROP_BOARD_INCOMPLETE"
        elif len(prop_indexes_by_team) >= 2:
            engine["prop_board_status"] = "AVAILABLE"
            engine["prop_board_error"] = None
            engine["failed_requested_teams"] = []

    all_rows = [row for game in games for row in game.get("rows") or []]
    out["rows"] = all_rows
    out["selected_rows"] = [row for row in all_rows if row.get("selected")]
    out["prop_board_safety_policy"] = {
        "two_sided_requested_teams_must_both_price": True,
        "failure_status": "NO_MODEL",
        "failure_reason_prefix": "GAME_PROP_SIMULATION_INCOMPLETE",
    }
    out["presentation_policy"] = {
        "market_probability_field": "market_no_vig_p",
        "model_probability_field": "estimate_p",
        "score_field": "score_0_100",
        "score_label_field": "score_label",
        "kickoff_field": "games[].kickoff",
        "team_records": "OMIT_UNLESS_EXPLICITLY_SOURCED",
    }
    return out


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

    ticket, alias_bindings = _normalize_ticket_prop_players(ticket, depth_rows)

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
    payload = _apply_prop_board_safety(payload, ticket)
    payload["source_status"] = source_status
    payload["schedule_source_sha256"] = plan.get("schedule_source_sha256")
    payload["player_alias_bindings"] = alias_bindings

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
