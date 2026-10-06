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


def _adapt_signed_yardage_for_nonnegative_v1(
    player_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Narrow compatibility copy for frozen V1 receiving efficiency.

    Preserve all signed source stats. In the in-memory model copy only, adapt a
    negative receiving-yard numerator when it comes from a 1-2 reception
    micro-sample. That fixes the CJ Donaldson shape without globally flooring
    passing/rushing yardage or larger receiving samples. Larger anomalies remain
    untouched and can still fail closed.
    """
    out: list[dict] = []
    receipts: list[dict] = []
    for raw in player_rows:
        row = dict(raw)
        try:
            receptions = float(row.get("receptions") or 0.0)
            receiving_yards = float(row.get("receiving_yards") or 0.0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if receiving_yards < 0 and 0 < receptions <= 2:
            row["receiving_yards"] = 0.0
            receipts.append({
                "player_id": str(row.get("player_id") or row.get("gsis_id") or ""),
                "player_name": str(row.get("player_name") or ""),
                "season": row.get("season"),
                "week": row.get("week"),
                "team": str(row.get("recent_team") or row.get("team") or ""),
                "field": "receiving_yards",
                "receptions": receptions,
                "source_value": receiving_yards,
                "model_input_value": 0.0,
                "reason": "FROZEN_V1_NEGATIVE_RECEIVING_MICRO_SAMPLE_COMPATIBILITY",
            })
        out.append(row)
    return out, receipts


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


_PROP_FAMILY = {
    "pass_attempts": "PASS_VOLUME",
    "completions": "PASS_VOLUME",
    "passing_yards": "PASS_VOLUME",
    "receptions": "RECEIVING_VOLUME",
    "receiving_yards": "RECEIVING_VOLUME",
    "rush_attempts": "RUSH_VOLUME",
    "rushing_yards": "RUSH_VOLUME",
    "rush_receiving_yards": "COMBINED_YARDS",
    "pass_tds": "PASS_SCORING",
    "interceptions": "TURNOVERS",
    "receiving_tds": "TD_SCORING",
    "rushing_tds": "TD_SCORING",
    "anytime_tds": "TD_SCORING",
}
_PROP_FAMILY_CONFLICTS = {
    "PASS_VOLUME": {"PASS_VOLUME"},
    "RECEIVING_VOLUME": {"RECEIVING_VOLUME", "COMBINED_YARDS"},
    "RUSH_VOLUME": {"RUSH_VOLUME", "COMBINED_YARDS"},
    "COMBINED_YARDS": {"RECEIVING_VOLUME", "RUSH_VOLUME", "COMBINED_YARDS"},
    "PASS_SCORING": {"PASS_SCORING"},
    "TURNOVERS": {"TURNOVERS"},
    "TD_SCORING": {"TD_SCORING"},
}
_MAX_SELECTED_PROP_FAMILIES_PER_PLAYER = 2
_MAX_SELECTED_TEAM_CLUSTER_EXPRESSIONS = 2
_PROP_TEAM_CLUSTER = {
    "PASS_VOLUME": "PASS_OFFENSE",
    "RECEIVING_VOLUME": "PASS_OFFENSE",
    "COMBINED_YARDS": "PASS_OFFENSE",
    "RUSH_VOLUME": "RUSH_OFFENSE",
    "PASS_SCORING": "SCORING",
    "TD_SCORING": "SCORING",
    "TURNOVERS": "TURNOVERS",
}


def _selection_rank(row: dict) -> tuple[float, float, float, int]:
    return (
        float(row.get("ev_per_dollar") or float("-inf")),
        float(row.get("edge_probability_points") or float("-inf")),
        float(row.get("score_0_100") or float("-inf")),
        -int(row.get("input_index") or 0),
    )


def _apply_correlation_selection_policy(game: dict, raw_game: dict) -> dict:
    """Trim the served card, never the underlying model probabilities.

    Pair-level selection can nominate several highly correlated expressions of
    the same player or team-offense thesis. Keep the strongest expressions within
    those correlation clusters. There is no arbitrary global prop-count cap, and
    this deliberately does NOT force team or over/under balance.
    """
    prop_indexes = {
        i for i, raw in enumerate(raw_game.get("markets") or [])
        if isinstance(raw, dict) and str(raw.get("player") or "").strip()
    }
    candidates = [
        row for row in game.get("rows") or []
        if row.get("selected")
        and int(row.get("input_index", -1)) in prop_indexes
        and str(row.get("player") or "").strip()
    ]
    for row in candidates:
        row["pair_selected"] = True

    used_families: dict[str, set[str]] = {}
    player_kept: dict[str, int] = {}
    team_cluster_kept: dict[tuple[str, str], int] = {}
    kept = 0
    suppressed: list[dict[str, str]] = []

    for row in sorted(candidates, key=_selection_rank, reverse=True):
        player = str(row.get("player") or "").strip()
        market = str(row.get("market") or "").strip().lower()
        family = _PROP_FAMILY.get(market, market.upper() or "OTHER")
        conflicts = _PROP_FAMILY_CONFLICTS.get(family, {family})
        prior = used_families.setdefault(player, set())
        team = str(row.get("team") or "").strip().lower()
        cluster = _PROP_TEAM_CLUSTER.get(family, family)
        cluster_key = (team, cluster)

        reason = None
        if prior.intersection(conflicts):
            reason = "CORRELATED_PLAYER_FAMILY"
        elif player_kept.get(player, 0) >= _MAX_SELECTED_PROP_FAMILIES_PER_PLAYER:
            reason = "PLAYER_PROP_EXPOSURE_CAP"
        elif (
            team in {"home", "away"}
            and team_cluster_kept.get(cluster_key, 0)
            >= _MAX_SELECTED_TEAM_CLUSTER_EXPRESSIONS
        ):
            reason = "CORRELATED_TEAM_OFFENSE_CLUSTER"

        if reason is not None:
            row["selected"] = False
            row["selection_suppressed_reason"] = reason
            suppressed.append({
                "player": player,
                "market": market,
                "reason": reason,
            })
            continue

        kept += 1
        player_kept[player] = player_kept.get(player, 0) + 1
        prior.add(family)
        if team in {"home", "away"}:
            team_cluster_kept[cluster_key] = team_cluster_kept.get(cluster_key, 0) + 1

    return {
        "candidate_pair_selections": len(candidates),
        "served_prop_selections": kept,
        "max_prop_families_per_player": _MAX_SELECTED_PROP_FAMILIES_PER_PLAYER,
        "max_team_cluster_expressions": _MAX_SELECTED_TEAM_CLUSTER_EXPRESSIONS,
        "global_prop_count_cap": None,
        "forces_team_balance": False,
        "forces_over_under_balance": False,
        "suppressed": suppressed,
    }


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
    pair_selected = [
        row for row in priced
        if row.get("pair_selected", row.get("selected", False))
    ]
    served_selected = [row for row in priced if row.get("selected")]
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
    for row in pair_selected:
        team = team_code(row)
        selected_team_counts[team] = selected_team_counts.get(team, 0) + 1
        side = direction(row)
        selected_direction_counts[side] = selected_direction_counts.get(side, 0) + 1

    alerts: list[str] = []
    n_selected = len(pair_selected)
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
        "pair_selected_prop_rows": n_selected,
        "served_selected_prop_rows": len(served_selected),
        "selected_prop_rows": n_selected,
        "priced_teams": priced_teams,
        "selected_team_counts": dict(sorted(selected_team_counts.items())),
        "selected_direction_counts": dict(sorted(selected_direction_counts.items())),
        "alerts": alerts,
        "review_required": bool(alerts),
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

        game["prop_selection_policy"] = _apply_correlation_selection_policy(game, raw_game)
        game["prop_selection_diagnostics"] = _prop_selection_diagnostics(game, raw_game)

    all_rows = [row for game in games for row in game.get("rows") or []]
    out["rows"] = all_rows
    out["selected_rows"] = [row for row in all_rows if row.get("selected")]
    out["prop_card_review_required"] = any(
        bool(game.get("prop_selection_diagnostics", {}).get("review_required"))
        for game in games
    )
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

    player_rows, signed_yardage_adaptations = _adapt_signed_yardage_for_nonnegative_v1(
        player_rows
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
    payload["signed_yardage_adaptations"] = signed_yardage_adaptations

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
