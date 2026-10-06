"""NFL_SCORE_COUNTS_G1 manual-board phone card.

Consumes a pre-market frozen score-count prediction, then binds two-sided
sportsbook quotes strictly downstream for no-vig comparison, EV and Score-B.
Game markets and player props are priced from the same 50,000 score paths.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior
from sportsedge.nfl_unified_phone import (
    EV_FLOOR,
    MAX_STRAIGHT_PRICE,
    UnifiedNflPhoneError,
    _decimal_pair,
    _decorate,
    _find_player,
    _game_flags,
    _mark_pair_selections,
    _match_schedule,
    _prop_flags,
    _utc,
)
from sportsedge.sports.nfl.live_role_source import build_live_team_model
from sportsedge.sports.nfl.score_counts_market_bridge import (
    price_score_count_game_markets,
    score_count_prediction_game,
)
from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_prop_markets,
)
from sportsedge.sports.nfl.unified_market_engine import TD_PROP_MARKETS

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_PHONE_CARD_V1"


_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}


def _team_code(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _filter_current_starter_qb_history(
    *,
    team: str,
    target_season: int,
    target_week: int,
    observed_at,
    depth_rows: Sequence[Mapping[str, Any]],
    player_rows: Sequence[Mapping[str, Any]],
    minimum_primary_games: int = 2,
    primary_attempt_share: float = 0.50,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Exclude clear backup/mop-up QB appearances from a current starter's role prior.

    The live role source otherwise averages the starter's last eight stat rows,
    even if some rows were tiny backup appearances. This PIT-only adapter keeps
    games where the current starter owned at least half of that team's QB pass
    attempts. It activates only with at least two qualifying prior games.
    """
    team_id = _team_code(team)
    snapshots: list[tuple[Any, Mapping[str, Any]]] = []
    for raw in depth_rows:
        if _team_code(raw.get("team") or raw.get("club_code")) != team_id:
            continue
        if raw.get("dt") in (None, ""):
            continue
        try:
            stamp = _utc(raw.get("dt"), "depth dt")
        except Exception:
            continue
        if stamp <= observed_at:
            snapshots.append((stamp, raw))
    if not snapshots:
        return list(player_rows), {
            "status": "NOT_APPLIED",
            "reason": "NO_PIT_DEPTH_SNAPSHOT",
            "team": team_id,
        }

    latest = max(stamp for stamp, _ in snapshots)
    qbs = []
    for stamp, raw in snapshots:
        if stamp != latest:
            continue
        position = str(raw.get("pos_abb") or raw.get("position") or "").strip().upper()
        rank = _as_int(raw.get("pos_rank"))
        pid = str(raw.get("gsis_id") or raw.get("player_id") or "").strip()
        if position in {"QB", "QUARTERBACK"} and rank == 1 and pid:
            qbs.append(pid)
    qbs = sorted(set(qbs))
    if len(qbs) != 1:
        return list(player_rows), {
            "status": "NOT_APPLIED",
            "reason": "STARTING_QB_NOT_UNIQUE",
            "team": team_id,
            "candidate_ids": qbs,
        }
    starter_id = qbs[0]

    prior_rows: list[Mapping[str, Any]] = []
    for raw in player_rows:
        season = _as_int(raw.get("season"))
        week = _as_int(raw.get("week"))
        if season is None or week is None:
            continue
        if str(raw.get("season_type") or "REG").strip().upper() != "REG":
            continue
        if season > target_season or (season == target_season and week >= target_week):
            continue
        prior_rows.append(raw)

    team_qb_attempts: dict[tuple[str, int, int], float] = {}
    for raw in prior_rows:
        position = str(raw.get("position") or "").strip().upper()
        if position not in {"QB", "QUARTERBACK"}:
            continue
        season = _as_int(raw.get("season"))
        week = _as_int(raw.get("week"))
        recent_team = _team_code(raw.get("recent_team") or raw.get("team"))
        if season is None or week is None or not recent_team:
            continue
        key = (recent_team, season, week)
        team_qb_attempts[key] = team_qb_attempts.get(key, 0.0) + max(
            0.0, _as_float(raw.get("attempts"))
        )

    primary_keys: set[tuple[str, int, int]] = set()
    starter_prior_rows = []
    for raw in prior_rows:
        pid = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        if pid != starter_id:
            continue
        season = _as_int(raw.get("season"))
        week = _as_int(raw.get("week"))
        recent_team = _team_code(raw.get("recent_team") or raw.get("team"))
        if season is None or week is None or not recent_team:
            continue
        key = (recent_team, season, week)
        total = team_qb_attempts.get(key, 0.0)
        attempts = max(0.0, _as_float(raw.get("attempts")))
        starter_prior_rows.append((key, attempts, total))
        if total > 0 and attempts / total >= float(primary_attempt_share):
            primary_keys.add(key)

    if len(primary_keys) < int(minimum_primary_games):
        return list(player_rows), {
            "status": "NOT_APPLIED",
            "reason": "INSUFFICIENT_PRIMARY_QB_GAMES",
            "team": team_id,
            "starter_qb_id": starter_id,
            "qualifying_games": len(primary_keys),
            "minimum_primary_games": int(minimum_primary_games),
        }

    filtered: list[Mapping[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for raw in player_rows:
        pid = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        season = _as_int(raw.get("season"))
        week = _as_int(raw.get("week"))
        is_prior = (
            season is not None and week is not None
            and (season < target_season or (season == target_season and week < target_week))
            and str(raw.get("season_type") or "REG").strip().upper() == "REG"
        )
        if pid != starter_id or not is_prior:
            filtered.append(raw)
            continue
        recent_team = _team_code(raw.get("recent_team") or raw.get("team"))
        key = (recent_team, season, week)
        if key in primary_keys:
            filtered.append(raw)
            continue
        removed.append({
            "season": season,
            "week": week,
            "team": recent_team,
            "attempts": _as_float(raw.get("attempts")),
            "team_qb_attempts": team_qb_attempts.get(key, 0.0),
        })

    return filtered, {
        "status": "APPLIED",
        "team": team_id,
        "starter_qb_id": starter_id,
        "primary_attempt_share": float(primary_attempt_share),
        "qualifying_games": len(primary_keys),
        "removed_nonprimary_games": removed,
    }


def _prediction_identity(
    prediction: Mapping[str, Any],
    *,
    game_id: str,
    away: str,
    home: str,
    observed_at,
) -> dict[str, Any]:
    prediction_at = _utc(prediction.get("prediction_at"), "prediction_at")
    if prediction_at >= observed_at:
        raise UnifiedNflPhoneError("SCORE_COUNT_PREDICTION_NOT_BEFORE_QUOTE_BINDING")
    game = score_count_prediction_game(prediction, game_id)
    game_prediction_at = _utc(game.get("prediction_at"), "game.prediction_at")
    kickoff = _utc(game.get("kickoff_at"), "game.kickoff_at")
    if game_prediction_at >= observed_at:
        raise UnifiedNflPhoneError("SCORE_COUNT_GAME_PREDICTION_NOT_BEFORE_QUOTE_BINDING")
    if not game_prediction_at < kickoff:
        raise UnifiedNflPhoneError("SCORE_COUNT_PREDICTION_NOT_PREGAME")
    if str(game.get("away_team") or "").strip().upper() != away:
        raise UnifiedNflPhoneError("SCORE_COUNT_AWAY_TEAM_MISMATCH")
    if str(game.get("home_team") or "").strip().upper() != home:
        raise UnifiedNflPhoneError("SCORE_COUNT_HOME_TEAM_MISMATCH")
    return game


def _meta(
    *,
    pair_id: str,
    input_index: int,
    side_index: int,
    selection: str,
    line: float | None,
    price: int,
    no_vig_p: float,
    raw: str,
    market: str,
    player: str | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "input_index": input_index,
        "side_index": side_index,
        "display_selection": selection,
        "display_line": line,
        "price": int(price),
        "market_no_vig_p": float(no_vig_p),
        "raw": raw,
        "market": market,
        "player": player,
        "position": position,
    }


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


def _selection_rank(row: Mapping[str, Any]) -> tuple[float, float, float, int]:
    return (
        float(row.get("ev_per_dollar") or float("-inf")),
        float(row.get("edge_probability_points") or float("-inf")),
        float(row.get("score_0_100") or float("-inf")),
        -int(row.get("input_index") or 0),
    )


def _apply_prop_selection_policy(
    rows: list[dict[str, Any]],
    raw_game: Mapping[str, Any],
) -> dict[str, Any]:
    prop_indexes = {
        i for i, raw in enumerate(raw_game.get("markets") or [])
        if isinstance(raw, Mapping) and str(raw.get("player") or "").strip()
    }
    candidates = [
        row for row in rows
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


def _prop_selection_diagnostics(
    rows: Sequence[Mapping[str, Any]],
    raw_game: Mapping[str, Any],
) -> dict[str, Any]:
    prop_indexes = {
        i for i, raw in enumerate(raw_game.get("markets") or [])
        if isinstance(raw, Mapping) and str(raw.get("player") or "").strip()
    }
    priced = [
        row for row in rows
        if int(row.get("input_index", -1)) in prop_indexes
        and row.get("status") == "PRICED"
    ]
    pair_selected = [
        row for row in priced
        if row.get("pair_selected", row.get("selected", False))
    ]
    served_selected = [row for row in priced if row.get("selected")]

    teams = {
        str(row.get("team") or "").strip().lower()
        for row in priced
        if str(row.get("team") or "").strip().lower() in {"home", "away"}
    }
    selected_teams = {
        str(row.get("team") or "").strip().lower()
        for row in pair_selected
        if str(row.get("team") or "").strip().lower() in {"home", "away"}
    }
    direction_counts = {"OVER": 0, "UNDER": 0}
    for row in pair_selected:
        value = str(row.get("selection") or "").strip().lower()
        if value.endswith(" over") or value == "over":
            direction_counts["OVER"] += 1
        elif value.endswith(" under") or value == "under":
            direction_counts["UNDER"] += 1

    alerts: list[str] = []
    n_selected = len(pair_selected)
    if len(teams) >= 2 and n_selected >= 4 and len(selected_teams) == 1:
        alerts.append("ALL_SELECTED_PROPS_ONE_TEAM_WITH_TWO_TEAM_PRICING")
    if n_selected >= 6:
        if direction_counts["UNDER"] / n_selected >= 0.80:
            alerts.append("SELECTED_PROP_DIRECTION_CONCENTRATED_UNDER")
        if direction_counts["OVER"] / n_selected >= 0.80:
            alerts.append("SELECTED_PROP_DIRECTION_CONCENTRATED_OVER")

    return {
        "priced_prop_rows": len(priced),
        "pair_selected_prop_rows": n_selected,
        "served_selected_prop_rows": len(served_selected),
        "selected_prop_rows": n_selected,
        "priced_sides": sorted(teams),
        "selected_sides": sorted(selected_teams),
        "selected_direction_counts": direction_counts,
        "alerts": alerts,
        "review_required": bool(alerts),
        "selection_changed_by_diagnostic": False,
    }


def build_score_count_phone_card(
    ticket: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any],
    schedule_games: Sequence[Mapping[str, Any]],
    depth_rows: Sequence[Mapping[str, Any]] = (),
    player_rows: Sequence[Mapping[str, Any]] = (),
    injury_rows: Sequence[Mapping[str, Any]] = (),
    injury_source_ready: bool = False,
    scoring_prior: ScoringCompositionPrior | None = None,
    seed: int = 21,
) -> dict[str, Any]:
    if not isinstance(ticket, Mapping):
        raise UnifiedNflPhoneError("TICKET_OBJECT_REQUIRED")
    if not isinstance(prediction, Mapping):
        raise UnifiedNflPhoneError("SCORE_COUNT_PREDICTION_OBJECT_REQUIRED")
    observed = _utc(ticket.get("observed_at"), "observed_at")
    games_out: list[dict[str, Any]] = []

    for game_index, raw_game in enumerate(ticket.get("games") or []):
        if not isinstance(raw_game, Mapping):
            raise UnifiedNflPhoneError("GAME_OBJECT_REQUIRED")
        away = str(raw_game.get("away") or "").strip().upper()
        home = str(raw_game.get("home") or "").strip().upper()
        schedule = _match_schedule(
            schedule_games,
            away=away,
            home=home,
            observed_at=observed,
        )
        kickoff = _utc(schedule["kickoff"], "kickoff")
        prediction_game = _prediction_identity(
            prediction,
            game_id=schedule["game_id"],
            away=away,
            home=home,
            observed_at=observed,
        )

        markets = [row for row in raw_game.get("markets") or [] if isinstance(row, Mapping)]
        prop_inputs = [row for row in markets if str(row.get("player") or "").strip()]
        td_prop_path_ready = (
            prediction_game.get("joint_score_td_distribution") is not None
            or scoring_prior is not None
        )
        modelable_prop_inputs = [
            row for row in prop_inputs
            if str(row.get("market") or "").strip().lower() not in TD_PROP_MARKETS
            or td_prop_path_ready
        ]
        home_model = away_model = None
        role_error: str | None = None
        role_errors_by_side: dict[str, str] = {}
        qb_role_filters_by_side: dict[str, dict[str, Any]] = {}
        hinted_teams = {
            str(row.get("team") or "").strip().upper()
            for row in modelable_prop_inputs
            if str(row.get("team") or "").strip().upper() in {home, away}
        }
        every_prop_hinted = bool(modelable_prop_inputs) and all(
            str(row.get("team") or "").strip().upper() in {home, away}
            for row in modelable_prop_inputs
        )
        requested_model_sides = (
            hinted_teams
            if every_prop_hinted
            else ({home, away} if modelable_prop_inputs else set())
        )

        if modelable_prop_inputs and not injury_source_ready:
            role_error = "INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS"
        elif modelable_prop_inputs:
            for side_name, team_name in (("home", home), ("away", away)):
                if team_name not in requested_model_sides:
                    continue
                try:
                    team_player_rows, qb_role_filter = _filter_current_starter_qb_history(
                        team=team_name,
                        target_season=int(schedule["season"]),
                        target_week=int(schedule["week"]),
                        observed_at=observed,
                        depth_rows=depth_rows,
                        player_rows=player_rows,
                    )
                    qb_role_filters_by_side[side_name] = qb_role_filter
                    model = build_live_team_model(
                        team=team_name,
                        target_season=int(schedule["season"]),
                        target_week=int(schedule["week"]),
                        kickoff=kickoff,
                        observed_at=observed,
                        depth_rows=depth_rows,
                        player_rows=team_player_rows,
                        injury_rows=injury_rows,
                    )
                    if side_name == "home":
                        home_model = model
                    else:
                        away_model = model
                except Exception as exc:
                    role_errors_by_side[side_name] = str(exc)

            needs_two_team_roles = (
                not every_prop_hinted
                or hinted_teams == {home, away}
            )
            if role_errors_by_side and needs_two_team_roles:
                detail = ";".join(
                    f"{side}={role_errors_by_side[side]}"
                    for side in sorted(role_errors_by_side)
                )
                role_error = f"GAME_PROP_ROLE_MODEL_INCOMPLETE:{detail}"

        game_requests: list[dict[str, Any]] = []
        prop_requests: list[dict[str, Any]] = []
        game_meta: list[dict[str, Any]] = []
        prop_meta: list[dict[str, Any]] = []

        for input_index, raw in enumerate(markets):
            market = str(raw.get("market") or "").strip().lower()
            no_vig, prices = _decimal_pair(raw)
            pair_id = f"{schedule['game_id']}:{input_index}:{market}"
            raw_text = str(raw.get("raw") or market)

            if market == "moneyline":
                specs = [
                    ({"market": "moneyline", "selection": "away"}, away, None),
                    ({"market": "moneyline", "selection": "home"}, home, None),
                ]
                for side_index, (request, label, line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append(_meta(
                        pair_id=pair_id, input_index=input_index, side_index=side_index,
                        selection=label, line=line, price=prices[side_index],
                        no_vig_p=no_vig[side_index], raw=raw_text, market=market,
                    ))
                continue

            if market == "spread":
                away_line = float(raw["line"])
                specs = [
                    ({"market": "spread", "selection": "away", "line": away_line}, away, away_line),
                    ({"market": "spread", "selection": "home", "line": -away_line}, home, -away_line),
                ]
                for side_index, (request, label, line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append(_meta(
                        pair_id=pair_id, input_index=input_index, side_index=side_index,
                        selection=label, line=line, price=prices[side_index],
                        no_vig_p=no_vig[side_index], raw=raw_text, market=market,
                    ))
                continue

            if market == "total":
                line = float(raw["line"])
                specs = [
                    ({"market": "total", "selection": "over", "line": line}, "Over", line),
                    ({"market": "total", "selection": "under", "line": line}, "Under", line),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append(_meta(
                        pair_id=pair_id, input_index=input_index, side_index=side_index,
                        selection=label, line=display_line, price=prices[side_index],
                        no_vig_p=no_vig[side_index], raw=raw_text, market=market,
                    ))
                continue

            if market == "team_total":
                line = float(raw["line"])
                team = str(raw.get("team") or "").strip().upper()
                if team not in {away, home}:
                    raise UnifiedNflPhoneError(f"TEAM_TOTAL_TEAM_NOT_IN_GAME:{team}")
                side = "home" if team == home else "away"
                specs = [
                    ({"market": "team_total", "team": side, "selection": "over", "line": line}, f"{team} Over", line),
                    ({"market": "team_total", "team": side, "selection": "under", "line": line}, f"{team} Under", line),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append(_meta(
                        pair_id=pair_id, input_index=input_index, side_index=side_index,
                        selection=label, line=display_line, price=prices[side_index],
                        no_vig_p=no_vig[side_index], raw=raw_text, market=market,
                    ))
                continue

            player = str(raw.get("player") or "").strip()
            if player:
                line = float(raw["line"])
                if market in TD_PROP_MARKETS and not td_prop_path_ready:
                    for side_index, label in enumerate(("Over", "Under")):
                        prop_meta.append({
                            **_meta(
                                pair_id=pair_id, input_index=input_index, side_index=side_index,
                                selection=f"{player} {label}", line=line,
                                price=prices[side_index], no_vig_p=no_vig[side_index],
                                raw=raw_text, market=market, player=player,
                            ),
                            "synthetic_no_model_reason": "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS",
                        })
                    continue
                if role_error is not None:
                    for side_index, label in enumerate(("Over", "Under")):
                        prop_meta.append({
                            **_meta(
                                pair_id=pair_id, input_index=input_index, side_index=side_index,
                                selection=f"{player} {label}", line=line,
                                price=prices[side_index], no_vig_p=no_vig[side_index],
                                raw=raw_text, market=market, player=player,
                            ),
                            "synthetic_no_model_reason": role_error,
                        })
                    continue
                team_hint = str(raw.get("team") or "").strip().upper()
                hinted_side = (
                    "home" if team_hint == home
                    else "away" if team_hint == away
                    else None
                )
                if hinted_side in role_errors_by_side:
                    reason = f"TEAM_ROLE_MODEL_UNAVAILABLE:{hinted_side}:{role_errors_by_side[hinted_side]}"
                    for side_index, label in enumerate(("Over", "Under")):
                        prop_meta.append({
                            **_meta(
                                pair_id=pair_id, input_index=input_index, side_index=side_index,
                                selection=f"{player} {label}", line=line,
                                price=prices[side_index], no_vig_p=no_vig[side_index],
                                raw=raw_text, market=market, player=player,
                            ),
                            "synthetic_no_model_reason": reason,
                        })
                    continue
                try:
                    team_side, canonical, position = _find_player(
                        player,
                        home_model=home_model,
                        away_model=away_model,
                    )
                except UnifiedNflPhoneError as exc:
                    for side_index, label in enumerate(("Over", "Under")):
                        prop_meta.append({
                            **_meta(
                                pair_id=pair_id, input_index=input_index, side_index=side_index,
                                selection=f"{player} {label}", line=line,
                                price=prices[side_index], no_vig_p=no_vig[side_index],
                                raw=raw_text, market=market, player=player,
                            ),
                            "synthetic_no_model_reason": str(exc),
                        })
                    continue
                for side_index, selection in enumerate(("over", "under")):
                    prop_requests.append({
                        "team": team_side,
                        "player": canonical,
                        "market": market,
                        "selection": selection,
                        "line": line,
                    })
                    prop_meta.append(_meta(
                        pair_id=pair_id, input_index=input_index, side_index=side_index,
                        selection=f"{canonical} {selection.title()}", line=line,
                        price=prices[side_index], no_vig_p=no_vig[side_index],
                        raw=raw_text, market=market, player=canonical, position=position,
                    ))
                continue

            raise UnifiedNflPhoneError(f"UNSUPPORTED_PHONE_MARKET:{market}")

        game_engine = price_score_count_game_markets(
            prediction,
            game_id=schedule["game_id"],
            requests=game_requests,
        )
        prop_engine = price_score_count_prop_markets(
            prediction,
            game_id=schedule["game_id"],
            prop_requests=prop_requests,
            home_model=home_model,
            away_model=away_model,
            scoring_prior=scoring_prior,
            seed=int(seed) + game_index,
        ) if prop_requests else {"prop_markets": []}
        engine_prop_error = (
            str(prop_engine.get("prop_board_error") or "").strip()
            if prop_requests
            else ""
        )
        effective_role_error = role_error or engine_prop_error or None

        rows: list[dict[str, Any]] = []
        for engine_row, meta in zip(game_engine["game_markets"], game_meta):
            rows.append(_decorate(
                engine_row,
                pair_id=meta["pair_id"],
                input_index=meta["input_index"],
                side_index=meta["side_index"],
                display_selection=meta["display_selection"],
                display_line=meta["display_line"],
                price=meta["price"],
                market_no_vig_p=meta["market_no_vig_p"],
                qualification_flags=_game_flags(),
                raw=meta["raw"],
            ))

        engine_prop_iter = iter(prop_engine.get("prop_markets") or [])
        for meta in prop_meta:
            if meta.get("synthetic_no_model_reason"):
                rows.append({
                    "pair_id": meta["pair_id"],
                    "input_index": meta["input_index"],
                    "side_index": meta["side_index"],
                    "market": meta["market"],
                    "selection": meta["display_selection"],
                    "line": meta["display_line"],
                    "player": meta.get("player"),
                    "price_american": meta["price"],
                    "market_no_vig_p": meta["market_no_vig_p"],
                    "raw": meta["raw"],
                    "selected": False,
                    "status": "NO_MODEL",
                    "reason": meta["synthetic_no_model_reason"],
                })
                continue
            engine_row = next(engine_prop_iter)
            rows.append(_decorate(
                engine_row,
                pair_id=meta["pair_id"],
                input_index=meta["input_index"],
                side_index=meta["side_index"],
                display_selection=meta["display_selection"],
                display_line=meta["display_line"],
                price=meta["price"],
                market_no_vig_p=meta["market_no_vig_p"],
                qualification_flags=_prop_flags(injury_ready=bool(injury_source_ready)),
                raw=meta["raw"],
            ))

        _mark_pair_selections(rows)
        prop_selection_policy = _apply_prop_selection_policy(rows, raw_game)
        prop_selection_diagnostics = _prop_selection_diagnostics(rows, raw_game)
        rows.sort(key=lambda row: (int(row["input_index"]), int(row["side_index"])))
        means = prediction_game.get("means") or {}
        games_out.append({
            **schedule,
            "prediction_at": prediction_game.get("prediction_at"),
            "forecast": {
                "home_score": means.get("home_score"),
                "away_score": means.get("away_score"),
                "margin": means.get("margin"),
                "total": means.get("total"),
                "source": "NFL_SCORE_COUNTS_G1_PREMARKET_PREDICTION",
                "creates_game_market_edge": True,
            },
            "engine": {
                "candidate_family": "NFL_SCORE_COUNTS_G1",
                "fit_artifact_sha256": prediction.get("fit_artifact_sha256"),
                "prediction_sha256": prediction.get("prediction_sha256"),
                "joint_score_distribution_sha256": prediction_game.get("joint_score_distribution_sha256"),
                "joint_score_td_distribution_sha256": prediction_game.get("joint_score_td_distribution_sha256"),
                "paths": prediction_game.get("paths"),
                "market_data_used_to_create_distribution": False,
                "prop_board_status": prop_engine.get("prop_board_status"),
                "prop_board_error": prop_engine.get("prop_board_error"),
                "team_simulation_errors": prop_engine.get("team_simulation_errors") or {},
                "role_model_errors_by_side": dict(sorted(role_errors_by_side.items())),
                "qb_role_filters_by_side": dict(sorted(qb_role_filters_by_side.items())),
            },
            "role_status": "AVAILABLE" if not effective_role_error else "NO_MODEL",
            "role_error": effective_role_error,
            "prop_selection_policy": prop_selection_policy,
            "prop_selection_diagnostics": prop_selection_diagnostics,
            "rows": rows,
            "status": "PRICED_SCORE_COUNTS_RESEARCH",
        })

    all_rows = [row for game in games_out for row in game.get("rows") or []]
    return {
        "schema": SCHEMA,
        "sport": "NFL",
        "observed_at": observed.isoformat(),
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "fit_artifact_sha256": prediction.get("fit_artifact_sha256"),
        "prediction_sha256": prediction.get("prediction_sha256"),
        "games": games_out,
        "rows": all_rows,
        "selected_rows": [row for row in all_rows if row.get("selected")],
        "prop_card_review_required": any(
            bool(game.get("prop_selection_diagnostics", {}).get("review_required"))
            for game in games_out
        ),
        "pricing_policy": {
            "two_sided_quotes_required": True,
            "ev_floor": EV_FLOOR,
            "straight_price_ceiling": MAX_STRAIGHT_PRICE,
            "score_uses_price_edge_ev": False,
            "live_props_require_injury_source": True,
            "game_markets_disabled": False,
            "model_distribution_must_predate_quote_binding": True,
            "prop_game_context_source": "NFL_SCORE_COUNTS_G1_SCORE_PATHS",
            "partial_team_simulation_fails_board": True,
            "correlated_player_prop_expressions_are_trimmed": True,
            "forces_team_balance": False,
            "forces_over_under_balance": False,
        },
        "presentation_policy": {
            "market_probability_field": "market_no_vig_p",
            "model_probability_field": "estimate_p",
            "score_field": "score_0_100",
            "score_label_field": "score_label",
            "kickoff_field": "games[].kickoff",
            "team_records": "OMIT_UNLESS_EXPLICITLY_SOURCED",
        },
        "authority": {
            "research_only": True,
            "not_truth_gate": True,
            "not_official": True,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }


__all__ = ["SCHEMA", "build_score_count_phone_card"]
