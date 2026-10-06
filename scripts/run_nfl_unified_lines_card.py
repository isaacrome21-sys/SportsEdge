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

from sportsedge.nfl_unified_phone import _match_schedule, _utc, build_unified_phone_card
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


_SIGNED_YARDAGE_FIELDS = ("passing_yards", "rushing_yards", "receiving_yards")


def _sanitize_signed_yardage_rows(player_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Adapt rare negative weekly yardage totals to nonnegative V1 efficiency support.

    Volume/count fields are untouched.  Only a negative yardage numerator is
    floored at zero because the current coherent passing/receiving simulator
    cannot allocate negative completed-pass yardage.  Every edit is emitted as
    an audit receipt so this is never a silent source rewrite.
    """
    out: list[dict] = []
    receipts: list[dict] = []
    for raw in player_rows:
        row = dict(raw)
        for field in _SIGNED_YARDAGE_FIELDS:
            value = row.get(field)
            if value in (None, "") or isinstance(value, bool):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric >= 0:
                continue
            receipts.append({
                "player_id": str(row.get("player_id") or row.get("gsis_id") or ""),
                "player_name": str(row.get("player_name") or ""),
                "season": row.get("season"),
                "week": row.get("week"),
                "team": str(row.get("recent_team") or row.get("team") or ""),
                "field": field,
                "original": numeric,
                "adapted": 0.0,
                "reason": "NONNEGATIVE_PROP_EFFICIENCY_SUPPORT",
            })
            row[field] = 0.0
        out.append(row)
    return out, receipts


ROLE_V2_MIN_CURRENT_GAMES = 4
ROLE_V2_PRIOR_ANCHOR_GAMES = 1
_ROLE_V2_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}


def _role_v2_team(value) -> str:
    raw = str(value or "").strip().upper()
    return _ROLE_V2_TEAM_ALIASES.get(raw, raw)


def _role_v2_active_ids(
    *,
    ticket: dict,
    depth_rows: list[dict],
    injury_rows: list[dict],
    target_season: int,
    target_week: int,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    observed = _utc(ticket.get("observed_at"), "observed_at")
    teams = {
        _role_v2_team(raw_game.get(key))
        for raw_game in ticket.get("games") or []
        for key in ("away", "home")
        if _role_v2_team(raw_game.get(key))
    }
    active: dict[str, set[str]] = {}
    snapshots: dict[str, str] = {}
    for team in sorted(teams):
        eligible: list[tuple[object, dict]] = []
        for raw in depth_rows:
            if _role_v2_team(raw.get("team") or raw.get("club_code")) != team:
                continue
            if raw.get("dt") in (None, ""):
                continue
            stamp = _utc(raw.get("dt"), "depth dt")
            if stamp <= observed:
                eligible.append((stamp, dict(raw)))
        if not eligible:
            raise SystemExit(f"NFL_ROLE_V2_DEPTH_SNAPSHOT_MISSING:{team}")
        latest = max(stamp for stamp, _ in eligible)
        snapshot = [row for stamp, row in eligible if stamp == latest]
        snapshots[team] = latest.isoformat()

        status_by_id: dict[str, tuple[object, str]] = {}
        for raw in injury_rows:
            if _role_v2_team(raw.get("team")) != team:
                continue
            try:
                season = int(float(raw.get("season")))
                week = int(float(raw.get("week")))
            except (TypeError, ValueError):
                continue
            if season != int(target_season) or week != int(target_week):
                continue
            pid = str(raw.get("gsis_id") or raw.get("player_id") or "").strip()
            if not pid or raw.get("date_modified") in (None, ""):
                continue
            stamp = _utc(raw.get("date_modified"), "injury date_modified")
            if stamp > observed:
                continue
            status = str(raw.get("report_status") or "").strip().upper() or "MISSING"
            prior = status_by_id.get(pid)
            if prior is None or stamp > prior[0]:
                status_by_id[pid] = (stamp, status)

        ids: set[str] = set()
        for row in snapshot:
            pid = str(row.get("gsis_id") or row.get("player_id") or "").strip()
            if not pid:
                continue
            status = status_by_id.get(pid, (None, "MISSING"))[1]
            if status in {"OUT", "INACTIVE"}:
                continue
            ids.add(pid)
        if not ids:
            raise SystemExit(f"NFL_ROLE_V2_ACTIVE_DEPTH_EMPTY:{team}")
        active[team] = ids
    return active, snapshots


def _filter_role_v2_current_team_history(
    player_rows: list[dict],
    *,
    active_ids_by_team: dict[str, set[str]],
) -> tuple[list[dict], list[dict]]:
    """Keep current-team usage mass only for players on the current active depth chart.

    Historical rows from a player's former team remain available to estimate that
    player's own role after a trade.  What is removed is stale usage credited to
    the current team by players who are no longer active there, preventing those
    departed/OUT players from silently becoming the synthetic OTHER receiver.
    """
    out: list[dict] = []
    removed: dict[tuple[str, str, str], int] = {}
    for raw in player_rows:
        row = dict(raw)
        team = _role_v2_team(row.get("recent_team") or row.get("team"))
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        if team in active_ids_by_team and pid and pid not in active_ids_by_team[team]:
            key = (team, pid, str(row.get("player_name") or ""))
            removed[key] = removed.get(key, 0) + 1
            continue
        out.append(row)
    receipts = [
        {
            "team": team,
            "player_id": pid,
            "player_name": name,
            "rows_removed": count,
            "reason": "NOT_ON_CURRENT_ACTIVE_DEPTH_SNAPSHOT",
        }
        for (team, pid, name), count in sorted(removed.items())
    ]
    return out, receipts


def _ticket_target_season_week(ticket: dict, schedule_games: list[dict]) -> tuple[int, int]:
    observed = _utc(ticket.get("observed_at"), "observed_at")
    targets: set[tuple[int, int]] = set()
    for raw_game in ticket.get("games") or []:
        away = str(raw_game.get("away") or "").strip().upper()
        home = str(raw_game.get("home") or "").strip().upper()
        matched = _match_schedule(
            schedule_games,
            away=away,
            home=home,
            observed_at=observed,
        )
        targets.add((int(matched["season"]), int(matched["week"])))
    if len(targets) != 1:
        raise SystemExit("NFL_ROLE_V2_SINGLE_SEASON_WEEK_REQUIRED")
    return next(iter(targets))


def _apply_role_v2_recency(
    player_rows: list[dict],
    *,
    target_season: int,
    target_week: int,
) -> tuple[list[dict], list[dict]]:
    """Early-season recency candidate: 4+ current games dominate stale prior roles.

    For a player with at least four strictly-prior games in the target season,
    retain all current-season rows plus only the single most recent older row as
    a prior anchor. Players with fewer than four current games keep the existing
    source history unchanged. The rule is player-local and market-blind.
    """
    grouped: dict[str, list[dict]] = {}
    passthrough: list[dict] = []
    for raw in player_rows:
        row = dict(raw)
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        if not pid:
            passthrough.append(row)
            continue
        grouped.setdefault(pid, []).append(row)

    kept: list[dict] = list(passthrough)
    receipts: list[dict] = []
    for pid, rows in grouped.items():
        def sw(row: dict) -> tuple[int, int]:
            try:
                return int(float(row.get("season"))), int(float(row.get("week")))
            except (TypeError, ValueError):
                return (-1, -1)

        ordered = sorted(rows, key=sw)
        current = [
            row for row in ordered
            if sw(row)[0] == int(target_season) and 0 < sw(row)[1] < int(target_week)
            and str(row.get("season_type") or "REG").strip().upper() == "REG"
        ]
        current_weeks = sorted({sw(row)[1] for row in current})
        if len(current_weeks) < ROLE_V2_MIN_CURRENT_GAMES:
            kept.extend(ordered)
            continue

        older = [
            row for row in ordered
            if sw(row)[0] < int(target_season)
            and str(row.get("season_type") or "REG").strip().upper() == "REG"
        ]
        anchors = older[-ROLE_V2_PRIOR_ANCHOR_GAMES:] if ROLE_V2_PRIOR_ANCHOR_GAMES else []
        chosen_ids = {id(row) for row in current + anchors}
        # Rows are copies, so identity is safe within this local list.
        selected = current + anchors
        kept.extend(selected)
        receipts.append({
            "player_id": pid,
            "player_name": str((current[-1] if current else ordered[-1]).get("player_name") or ""),
            "current_season_games": len(current_weeks),
            "prior_anchor_games": len(anchors),
            "source_rows_before": len(ordered),
            "source_rows_after": len(selected),
            "mode": "CURRENT_SEASON_PLUS_ONE_PRIOR_ANCHOR",
        })

    kept.sort(key=lambda row: (
        int(float(row.get("season") or -1)) if str(row.get("season") or "").replace(".", "", 1).isdigit() else -1,
        int(float(row.get("week") or -1)) if str(row.get("week") or "").replace(".", "", 1).isdigit() else -1,
        str(row.get("player_id") or row.get("gsis_id") or ""),
    ))
    return kept, sorted(receipts, key=lambda row: row["player_id"])


_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# Only failures produced while building/simulating a whole team should suppress
# the opposite side.  A single alias miss, unsupported market, or missing TD
# prior remains local to that player/market.
_TEAM_FATAL_REASON_PREFIXES = (
    "ROLE_VALUE_INVALID:",
    "TEAM_MODEL_REQUIRED",
    "TEAM_QB_REQUIRED",
    "TEAM_SKILL_PLAYERS_REQUIRED",
    "TEAM_SKILL_PLAYER_OBJECT_REQUIRED",
    "TEAM_PLAYER_IDENTITY_DUPLICATE",
    "RECEIVER_WEIGHT_REQUIRED",
    "RECEIVING_YARD_WEIGHT_REQUIRED",
    "CONTEXT_SCRIPT_MULTIPLIER_CONFLICT",
    "SCRIPT_SOURCE_REQUIRED",
    "SCRIPT_MULTIPLIER_REQUIRED:",
    "SCRIPT_MULTIPLIER_OUT_OF_RANGE:",
    "PASSING_YARDS_NEGATIVE",
)


def _team_fatal_reason(team_rows: list[dict]) -> str | None:
    """Identify a team-simulation crash while ignoring unrelated row-local misses."""
    if not team_rows or any(row.get("status") == "PRICED" for row in team_rows):
        return None
    reasons = {
        str(row.get("reason") or "").strip()
        for row in team_rows
        if str(row.get("reason") or "").strip()
    }
    fatal = sorted(
        reason for reason in reasons
        if reason.startswith(_TEAM_FATAL_REASON_PREFIXES)
    )
    if not fatal:
        return None
    if len(fatal) == 1:
        return fatal[0]
    return "MULTIPLE_TEAM_SIMULATION_ERRORS:" + "|".join(fatal)


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


def _prop_selection_diagnostics(game: dict, raw_game: dict) -> dict:
    prop_indexes = {
        i for i, raw in enumerate(raw_game.get("markets") or [])
        if isinstance(raw, dict) and str(raw.get("player") or "").strip()
    }
    rows = [
        row for row in game.get("rows") or []
        if int(row.get("input_index", -1)) in prop_indexes
    ]
    priced = [row for row in rows if row.get("status") == "PRICED"]
    selected = [row for row in priced if row.get("selected")]
    home = str(raw_game.get("home") or "").strip().upper()
    away = str(raw_game.get("away") or "").strip().upper()

    def team_code(row: dict) -> str:
        side = str(row.get("team") or "").strip().lower()
        return home if side == "home" else away if side == "away" else "UNKNOWN"

    def direction(row: dict) -> str:
        value = str(row.get("selection") or row.get("display_selection") or "").strip().lower()
        if value.endswith(" under") or value == "under":
            return "UNDER"
        if value.endswith(" over") or value == "over":
            return "OVER"
        return "OTHER"

    priced_teams = sorted({team_code(row) for row in priced if team_code(row) != "UNKNOWN"})
    selected_team_counts: dict[str, int] = {}
    selected_direction_counts: dict[str, int] = {}
    for row in selected:
        team = team_code(row)
        selected_team_counts[team] = selected_team_counts.get(team, 0) + 1
        side = direction(row)
        selected_direction_counts[side] = selected_direction_counts.get(side, 0) + 1

    alerts: list[str] = []
    n_selected = len(selected)
    if len(priced_teams) >= 2 and n_selected >= 4 and len({
        team for team, count in selected_team_counts.items()
        if team != "UNKNOWN" and count > 0
    }) == 1:
        alerts.append("ALL_SELECTED_PROPS_ONE_TEAM_WITH_TWO_TEAM_PRICING")
    if n_selected >= 6:
        unders = selected_direction_counts.get("UNDER", 0)
        overs = selected_direction_counts.get("OVER", 0)
        if unders / n_selected >= 0.80:
            alerts.append("SELECTED_PROP_DIRECTION_CONCENTRATED_UNDER")
        if overs / n_selected >= 0.80:
            alerts.append("SELECTED_PROP_DIRECTION_CONCENTRATED_OVER")

    return {
        "priced_prop_rows": len(priced),
        "selected_prop_rows": n_selected,
        "priced_teams": priced_teams,
        "selected_team_counts": dict(sorted(selected_team_counts.items())),
        "selected_direction_counts": dict(sorted(selected_direction_counts.items())),
        "alerts": alerts,
        "selection_changed_by_diagnostic": False,
    }


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

        failed_teams: dict[str, str] = {}
        degraded_teams: dict[str, list[str]] = {}
        if len(prop_indexes_by_team) >= 2:
            for team, indexes in sorted(prop_indexes_by_team.items()):
                team_rows = [
                    row for row in rows
                    if int(row.get("input_index", -1)) in indexes
                ]
                fatal = _team_fatal_reason(team_rows)
                if fatal is not None:
                    failed_teams[team] = fatal
                elif not any(row.get("status") == "PRICED" for row in team_rows):
                    degraded_teams[team] = sorted({
                        str(row.get("reason") or "NO_MODEL")
                        for row in team_rows
                    })

        engine = game.setdefault("engine", {})
        if failed_teams:
            detail = ";".join(
                f"{team}={failed_teams[team]}"
                for team in sorted(failed_teams)
            )
            reason = f"GAME_PROP_SIMULATION_INCOMPLETE:{detail}"
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
            engine["failed_requested_teams"] = sorted(failed_teams)
            engine["team_simulation_errors"] = dict(sorted(failed_teams.items()))
            engine["degraded_requested_teams"] = dict(sorted(degraded_teams.items()))
            game["role_status"] = "NO_MODEL"
            game["role_error"] = reason
            game["prop_status"] = "NO_MODEL_PROP_BOARD_INCOMPLETE"
        elif len(prop_indexes_by_team) >= 2:
            engine["prop_board_status"] = "AVAILABLE"
            engine["prop_board_error"] = None
            engine["failed_requested_teams"] = []
            engine["team_simulation_errors"] = {}
            engine["degraded_requested_teams"] = dict(sorted(degraded_teams.items()))
            game["prop_status"] = "AVAILABLE"

        game["prop_selection_diagnostics"] = _prop_selection_diagnostics(game, raw_game)

    all_rows = [row for game in games for row in game.get("rows") or []]
    out["rows"] = all_rows
    out["selected_rows"] = [row for row in all_rows if row.get("selected")]
    out["prop_board_safety_policy"] = {
        "team_simulation_failure_invalidates_two_team_board": True,
        "individual_player_or_market_no_model_does_not_invalidate_opposite_team": True,
        "single_team_quote_board_allowed": True,
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

    player_rows, signed_yardage_receipts = _sanitize_signed_yardage_rows(player_rows)
    role_v2_season, role_v2_week = _ticket_target_season_week(ticket, schedule_games)
    role_v2_active, role_v2_depth_snapshots = _role_v2_active_ids(
        ticket=ticket,
        depth_rows=depth_rows,
        injury_rows=injury_rows,
        target_season=role_v2_season,
        target_week=role_v2_week,
    )
    player_rows, role_v2_roster_receipts = _filter_role_v2_current_team_history(
        player_rows,
        active_ids_by_team=role_v2_active,
    )
    player_rows, role_v2_receipts = _apply_role_v2_recency(
        player_rows,
        target_season=role_v2_season,
        target_week=role_v2_week,
    )
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
    payload["signed_yardage_adaptations"] = signed_yardage_receipts
    payload["role_model_candidate"] = {
        "family": "NFL_MARKET_CONTEXT_PROP_V2_RECENCY",
        "target_season": role_v2_season,
        "target_week": role_v2_week,
        "min_current_games": ROLE_V2_MIN_CURRENT_GAMES,
        "prior_anchor_games": ROLE_V2_PRIOR_ANCHOR_GAMES,
        "player_receipts": role_v2_receipts,
        "depth_snapshot_asof_by_team": role_v2_depth_snapshots,
        "active_depth_player_count_by_team": {
            team: len(ids) for team, ids in sorted(role_v2_active.items())
        },
        "stale_or_unavailable_current_team_history_removed": role_v2_roster_receipts,
        "market_data_used": False,
        "research_only": True,
    }

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
