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

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_PHONE_CARD_V1"


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
        home_model = away_model = None
        role_error: str | None = None
        role_errors_by_side: dict[str, str] = {}
        hinted_teams = {
            str(row.get("team") or "").strip().upper()
            for row in prop_inputs
            if str(row.get("team") or "").strip().upper() in {home, away}
        }
        every_prop_hinted = bool(prop_inputs) and all(
            str(row.get("team") or "").strip().upper() in {home, away}
            for row in prop_inputs
        )
        requested_model_sides = (
            hinted_teams
            if every_prop_hinted
            else ({home, away} if prop_inputs else set())
        )

        if prop_inputs and not injury_source_ready:
            role_error = "INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS"
        elif prop_inputs:
            for side_name, team_name in (("home", home), ("away", away)):
                if team_name not in requested_model_sides:
                    continue
                try:
                    model = build_live_team_model(
                        team=team_name,
                        target_season=int(schedule["season"]),
                        target_week=int(schedule["week"]),
                        kickoff=kickoff,
                        observed_at=observed,
                        depth_rows=depth_rows,
                        player_rows=player_rows,
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
            },
            "role_status": "AVAILABLE" if not effective_role_error else "NO_MODEL",
            "role_error": effective_role_error,
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
