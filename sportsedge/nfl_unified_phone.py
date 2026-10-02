"""Build an MLB-style NFL phone board from the unified research engine.

This layer binds two-sided sportsbook quotes only after independent game/player
probabilities exist.  It never feeds prices back into the model.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import devig
from sportsedge.nfl_attempt9_live_forecast import (
    load_runtime,
    raw_forecasts,
    recency_features,
)
from sportsedge.nfl_run_it_scoring import price_run_it_pick
from sportsedge.sports.nfl.live_role_source import build_live_team_model
from sportsedge.sports.nfl.unified_market_engine import run_unified_nfl_model
from sportsedge.truth_gate import american_to_decimal

SCHEMA = "SPORTSEDGE_NFL_UNIFIED_PHONE_CARD_V1"
EV_FLOOR = 0.02
MAX_STRAIGHT_PRICE = -165


class UnifiedNflPhoneError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise UnifiedNflPhoneError(f"{field}:INVALID_TIMESTAMP") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise UnifiedNflPhoneError(f"{field}:AWARE_TIMESTAMP_REQUIRED")
    return out.astimezone(timezone.utc)


def _history_rows(raw: object) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping) and isinstance(raw.get("games"), list):
        return [row for row in raw["games"] if isinstance(row, Mapping)]
    return []


def _schedule_fields(row: Mapping[str, Any]) -> tuple[str, str, str, int, int, str]:
    game_id = str(row.get("game_id") or row.get("id") or "").strip()
    away = str(row.get("away_team_id") or row.get("away") or row.get("away_team") or "").strip().upper()
    home = str(row.get("home_team_id") or row.get("home") or row.get("home_team") or "").strip().upper()
    kickoff = str(row.get("kickoff_ts") or row.get("kickoff") or row.get("commence_time") or "").strip()
    try:
        season = int(float(row.get("season")))
        week = int(float(row.get("week")))
    except (TypeError, ValueError) as exc:
        raise UnifiedNflPhoneError("SCHEDULE_SEASON_WEEK_REQUIRED") from exc
    if not game_id or not away or not home or not kickoff:
        raise UnifiedNflPhoneError("SCHEDULE_IDENTITY_INCOMPLETE")
    return game_id, away, home, season, week, kickoff


def _match_schedule(
    schedule_games: Sequence[Mapping[str, Any]],
    *,
    away: str,
    home: str,
    observed_at: datetime,
) -> dict[str, Any]:
    matches = []
    for row in schedule_games:
        try:
            game_id, row_away, row_home, season, week, kickoff = _schedule_fields(row)
            kick = _utc(kickoff, "kickoff")
        except UnifiedNflPhoneError:
            continue
        if row_away == away and row_home == home and kick > observed_at:
            matches.append({
                "game_id": game_id,
                "away": row_away,
                "home": row_home,
                "season": season,
                "week": week,
                "kickoff": kick.isoformat(),
            })
    if len(matches) != 1:
        raise UnifiedNflPhoneError(
            f"SCHEDULE_MATCH_REQUIRED:{away}@{home}:matches={len(matches)}"
        )
    return matches[0]


def _name_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_player(
    player: str,
    *,
    home_model: Mapping[str, Any],
    away_model: Mapping[str, Any],
) -> tuple[str, str, str]:
    needle = _name_key(player)
    hits: list[tuple[str, str, str]] = []
    for side, model in (("home", home_model), ("away", away_model)):
        qb = model.get("qb") if isinstance(model, Mapping) else None
        rows = []
        if isinstance(qb, Mapping):
            rows.append(qb)
        skills = model.get("skill_players") if isinstance(model, Mapping) else None
        if isinstance(skills, Sequence) and not isinstance(skills, (str, bytes, bytearray)):
            rows.extend(row for row in skills if isinstance(row, Mapping))
        for row in rows:
            canonical = str(row.get("player") or "").strip()
            if not canonical or canonical.endswith("_OTHER"):
                continue
            if _name_key(canonical) == needle:
                hits.append((side, canonical, str(row.get("position") or "").upper()))
    if len(hits) != 1:
        raise UnifiedNflPhoneError(f"PROP_PLAYER_EXACT_MATCH_REQUIRED:{player}:matches={len(hits)}")
    return hits[0]


def _decimal_pair(raw: Mapping[str, Any]) -> tuple[list[float], list[int]]:
    try:
        prices = [int(raw["away_or_over_price"]), int(raw["home_or_under_price"])]
    except (KeyError, TypeError, ValueError) as exc:
        raise UnifiedNflPhoneError("TWO_SIDED_PRICES_REQUIRED") from exc
    probs = devig([american_to_decimal(prices[0]), american_to_decimal(prices[1])])
    return [float(probs[0]), float(probs[1])], prices


def _game_flags() -> dict[str, bool]:
    return {
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": False,
        "matchup_supported": True,
        "injury_context_ready": False,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }


def _prop_flags(*, injury_ready: bool) -> dict[str, bool]:
    return {
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": False,
        "injury_context_ready": bool(injury_ready),
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }


def _straight_price_allowed(price: int) -> bool:
    return price >= MAX_STRAIGHT_PRICE


def _decorate(
    engine_row: Mapping[str, Any],
    *,
    pair_id: str,
    input_index: int,
    side_index: int,
    display_selection: str,
    display_line: float | None,
    price: int,
    market_no_vig_p: float,
    qualification_flags: Mapping[str, bool],
    raw: str,
) -> dict[str, Any]:
    base = {
        "pair_id": pair_id,
        "input_index": input_index,
        "side_index": side_index,
        "market": engine_row.get("market"),
        "selection": display_selection,
        "line": display_line,
        "player": engine_row.get("player"),
        "team": engine_row.get("team"),
        "price_american": int(price),
        "market_no_vig_p": float(market_no_vig_p),
        "raw": raw,
        "selected": False,
    }
    if engine_row.get("status") != "PRICED_RESEARCH":
        return {
            **base,
            "status": "NO_MODEL",
            "reason": engine_row.get("reason") or engine_row.get("status") or "UNPRICED",
        }
    priced = price_run_it_pick(
        estimate_p=float(engine_row["estimate_p"]),
        push_p=float(engine_row.get("push_p") or 0.0),
        price_american=int(price),
        market_no_vig_p=float(market_no_vig_p),
        qualification_flags=qualification_flags,
    )
    card_eligible = (
        priced.ev_per_dollar >= EV_FLOOR
        and priced.edge_probability_points > 0.0
        and _straight_price_allowed(int(price))
    )
    reason = None
    if not _straight_price_allowed(int(price)):
        reason = "PRICE_ABOVE_STRAIGHT_CEILING"
    elif priced.ev_per_dollar < EV_FLOOR:
        reason = "EV_BELOW_2_PERCENT"
    elif priced.edge_probability_points <= 0:
        reason = "NO_POSITIVE_NO_VIG_EDGE"
    return {
        **base,
        "status": "PRICED",
        "estimate_p": priced.estimate_p,
        "push_p": priced.push_p,
        "loss_p": priced.loss_p,
        "conditional_win_probability": priced.fair_probability,
        "fair_american": priced.fair_american,
        "edge_probability_points": priced.edge_probability_points,
        "ev_per_dollar": priced.ev_per_dollar,
        "score_0_100": priced.score_0_100,
        "score_label": priced.score_label,
        "card_eligible": card_eligible,
        "card_reason": reason,
    }


def _mark_pair_selections(rows: list[dict[str, Any]]) -> None:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault(str(row["pair_id"]), []).append(row)
    for pair in by_pair.values():
        eligible = [row for row in pair if row.get("status") == "PRICED" and row.get("card_eligible")]
        if not eligible:
            continue
        keeper = max(
            eligible,
            key=lambda row: (
                float(row.get("ev_per_dollar") or float("-inf")),
                float(row.get("edge_probability_points") or float("-inf")),
                -int(row.get("side_index") or 0),
            ),
        )
        keeper["selected"] = True


def build_unified_phone_card(
    ticket: Mapping[str, Any],
    *,
    history: object,
    schedule_games: Sequence[Mapping[str, Any]],
    depth_rows: Sequence[Mapping[str, Any]] = (),
    player_rows: Sequence[Mapping[str, Any]] = (),
    injury_rows: Sequence[Mapping[str, Any]] = (),
    injury_source_ready: bool = False,
    runtime: Mapping[str, Any] | None = None,
    n_sims: int = 20000,
    seed: int = 21,
) -> dict[str, Any]:
    """Price one full pasted board from a single model run per game."""
    if not isinstance(ticket, Mapping):
        raise UnifiedNflPhoneError("TICKET_OBJECT_REQUIRED")
    observed = _utc(ticket.get("observed_at"), "observed_at")
    history_rows = _history_rows(history)
    model = dict(runtime or load_runtime())
    games_out: list[dict[str, Any]] = []

    for game_index, game in enumerate(ticket.get("games") or []):
        if not isinstance(game, Mapping):
            raise UnifiedNflPhoneError("GAME_OBJECT_REQUIRED")
        away = str(game.get("away") or "").strip().upper()
        home = str(game.get("home") or "").strip().upper()
        schedule = _match_schedule(
            schedule_games,
            away=away,
            home=home,
            observed_at=observed,
        )
        kickoff = _utc(schedule["kickoff"], "kickoff")
        feat = recency_features(
            history_rows,
            home=home,
            away=away,
            asof=kickoff.date(),
        )
        if not feat.get("ok"):
            games_out.append({
                **schedule,
                "features": feat,
                "rows": [],
                "status": "NO_MODEL",
                "reason": feat.get("reason") or "ATTEMPT9_FEATURES_UNAVAILABLE",
            })
            continue
        forecast = raw_forecasts(model, feat["vector"])

        markets = [row for row in game.get("markets") or [] if isinstance(row, Mapping)]
        prop_inputs = [row for row in markets if str(row.get("player") or "").strip()]
        home_model = away_model = None
        role_error = None
        if prop_inputs and not injury_source_ready:
            role_error = "INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS"
        elif prop_inputs:
            try:
                home_model = build_live_team_model(
                    team=home,
                    target_season=int(schedule["season"]),
                    target_week=int(schedule["week"]),
                    kickoff=kickoff,
                    observed_at=observed,
                    depth_rows=depth_rows,
                    player_rows=player_rows,
                    injury_rows=injury_rows,
                )
                away_model = build_live_team_model(
                    team=away,
                    target_season=int(schedule["season"]),
                    target_week=int(schedule["week"]),
                    kickoff=kickoff,
                    observed_at=observed,
                    depth_rows=depth_rows,
                    player_rows=player_rows,
                    injury_rows=injury_rows,
                )
            except Exception as exc:
                role_error = str(exc)

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
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                        "display_selection": label, "display_line": display_line,
                        "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "spread":
                away_line = float(raw["line"])
                home_handicap = -away_line
                specs = [
                    ({"market": "spread", "selection": "away", "line": away_line}, away, away_line),
                    ({"market": "spread", "selection": "home", "line": home_handicap}, home, home_handicap),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                        "display_selection": label, "display_line": display_line,
                        "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "total":
                line = float(raw["line"])
                specs = [
                    ({"market": "total", "selection": "over", "line": line}, "Over", line),
                    ({"market": "total", "selection": "under", "line": line}, "Under", line),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                        "display_selection": label, "display_line": display_line,
                        "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "team_total":
                line = float(raw["line"])
                team = str(raw.get("team") or "").upper()
                if team not in {away, home}:
                    raise UnifiedNflPhoneError(f"TEAM_TOTAL_TEAM_NOT_IN_GAME:{team}")
                side = "home" if team == home else "away"
                specs = [
                    ({"market": "team_total", "team": side, "selection": "over", "line": line}, f"{team} Over", line),
                    ({"market": "team_total", "team": side, "selection": "under", "line": line}, f"{team} Under", line),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                        "display_selection": label, "display_line": display_line,
                        "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            player = str(raw.get("player") or "").strip()
            if player:
                if role_error is not None or home_model is None or away_model is None:
                    for side_index, label in enumerate(("Over", "Under")):
                        prop_meta.append({
                            "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                            "display_selection": f"{player} {label}", "display_line": float(raw["line"]),
                            "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                            "raw": raw_text, "synthetic_no_model_reason": role_error or "LIVE_ROLE_MODEL_REQUIRED",
                            "market": market, "player": player,
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
                            "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                            "display_selection": f"{player} {label}", "display_line": float(raw["line"]),
                            "price": prices[side_index], "market_no_vig_p": no_vig[side_index],
                            "raw": raw_text, "synthetic_no_model_reason": str(exc),
                            "market": market, "player": player,
                        })
                    continue
                line = float(raw["line"])
                for side_index, selection in enumerate(("over", "under")):
                    prop_requests.append({
                        "team": team_side,
                        "player": canonical,
                        "market": market,
                        "selection": selection,
                        "line": line,
                    })
                    prop_meta.append({
                        "pair_id": pair_id, "input_index": input_index, "side_index": side_index,
                        "display_selection": f"{canonical} {selection.title()}",
                        "display_line": line, "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index], "raw": raw_text,
                        "position": position,
                    })
                continue

            raise UnifiedNflPhoneError(f"UNSUPPORTED_PHONE_MARKET:{market}")

        engine = run_unified_nfl_model(
            game_id=schedule["game_id"],
            home_team=home,
            away_team=away,
            attempt9_margin=float(forecast["margin"]),
            attempt9_total=float(forecast["total"]),
            game_markets=game_requests,
            prop_markets=prop_requests,
            home_model=home_model,
            away_model=away_model,
            scoring_prior=None,
            n_sims=int(n_sims),
            seed=int(seed) + game_index,
        )

        rows: list[dict[str, Any]] = []
        for engine_row, meta in zip(engine["game_markets"], game_meta):
            rows.append(_decorate(
                engine_row,
                pair_id=meta["pair_id"], input_index=meta["input_index"],
                side_index=meta["side_index"], display_selection=meta["display_selection"],
                display_line=meta["display_line"], price=meta["price"],
                market_no_vig_p=meta["market_no_vig_p"],
                qualification_flags=_game_flags(), raw=meta["raw"],
            ))

        engine_prop_iter = iter(engine["prop_markets"])
        for meta in prop_meta:
            if meta.get("synthetic_no_model_reason"):
                rows.append({
                    "pair_id": meta["pair_id"], "input_index": meta["input_index"],
                    "side_index": meta["side_index"], "market": meta.get("market"),
                    "selection": meta["display_selection"], "line": meta["display_line"],
                    "player": meta.get("player"), "price_american": meta["price"],
                    "market_no_vig_p": meta["market_no_vig_p"], "raw": meta["raw"],
                    "selected": False, "status": "NO_MODEL",
                    "reason": meta["synthetic_no_model_reason"],
                })
                continue
            engine_row = next(engine_prop_iter)
            rows.append(_decorate(
                engine_row,
                pair_id=meta["pair_id"], input_index=meta["input_index"],
                side_index=meta["side_index"], display_selection=meta["display_selection"],
                display_line=meta["display_line"], price=meta["price"],
                market_no_vig_p=meta["market_no_vig_p"],
                qualification_flags=_prop_flags(injury_ready=bool(injury_source_ready)),
                raw=meta["raw"],
            ))

        _mark_pair_selections(rows)
        rows.sort(key=lambda row: (int(row["input_index"]), int(row["side_index"])))
        games_out.append({
            **schedule,
            "features": feat,
            "forecast": forecast,
            "engine": {
                "schema": engine["schema"],
                "score_distribution": engine["score_distribution"],
                "workload_coupling": engine["workload_coupling"],
                "authority": engine["authority"],
            },
            "role_status": "AVAILABLE" if not role_error and (not prop_inputs or home_model is not None) else "NO_MODEL",
            "role_error": role_error,
            "rows": rows,
            "status": "PRICED",
        })

    all_rows = [row for game in games_out for row in game.get("rows") or []]
    return {
        "schema": SCHEMA,
        "sport": "NFL",
        "observed_at": observed.isoformat(),
        "games": games_out,
        "rows": all_rows,
        "selected_rows": [row for row in all_rows if row.get("selected")],
        "pricing_policy": {
            "two_sided_quotes_required": True,
            "ev_floor": EV_FLOOR,
            "straight_price_ceiling": MAX_STRAIGHT_PRICE,
            "score_uses_price_edge_ev": False,
            "live_props_require_injury_source": True,
        },
        "authority": {
            "research_only": True,
            "not_truth_gate": True,
            "not_official": True,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }


__all__ = [
    "EV_FLOOR",
    "MAX_STRAIGHT_PRICE",
    "SCHEMA",
    "UnifiedNflPhoneError",
    "build_unified_phone_card",
]
