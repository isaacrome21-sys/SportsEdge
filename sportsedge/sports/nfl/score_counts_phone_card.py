"""Bind a frozen NFL_SCORE_COUNTS_G1 prediction to a manual two-sided board.

The model prediction must already exist before the quote observation timestamp.
Sportsbook prices are used only for no-vig comparison, EV, and card eligibility;
they never feed the score distribution or player simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import devig
from sportsedge.nfl_run_it_scoring import price_run_it_pick
from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior
from sportsedge.truth_gate import american_to_decimal
from sportsedge.sports.nfl.score_counts_market_bridge import (
    price_score_count_game_markets,
    score_count_prediction_game,
)
from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_prop_markets,
)

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_PHONE_CARD_V1"
EV_FLOOR = 0.02
MAX_STRAIGHT_PRICE = -165
GAME_MARKETS = frozenset({"moneyline", "spread", "total", "team_total"})


class ScoreCountPhoneCardError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        out = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as exc:
        raise ScoreCountPhoneCardError(f"{field}:INVALID_TIMESTAMP") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ScoreCountPhoneCardError(f"{field}:AWARE_TIMESTAMP_REQUIRED")
    return out.astimezone(timezone.utc)


def _decimal_pair(raw: Mapping[str, Any]) -> tuple[list[float], list[int]]:
    try:
        prices = [
            int(raw["away_or_over_price"]),
            int(raw["home_or_under_price"]),
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ScoreCountPhoneCardError("TWO_SIDED_PRICES_REQUIRED") from exc
    probs = devig(
        [american_to_decimal(prices[0]), american_to_decimal(prices[1])]
    )
    return [float(probs[0]), float(probs[1])], prices


def _prediction_game_for_matchup(
    prediction: Mapping[str, Any],
    *,
    away: str,
    home: str,
) -> dict[str, Any]:
    games = prediction.get("games")
    if not isinstance(games, Sequence) or isinstance(
        games, (str, bytes, bytearray)
    ):
        raise ScoreCountPhoneCardError("PREDICTION_GAMES_REQUIRED")
    matches = [
        dict(row)
        for row in games
        if isinstance(row, Mapping)
        and str(row.get("away_team") or "").strip().upper() == away
        and str(row.get("home_team") or "").strip().upper() == home
    ]
    if len(matches) != 1:
        raise ScoreCountPhoneCardError(
            f"PREDICTION_MATCH_REQUIRED:{away}@{home}:matches={len(matches)}"
        )
    return matches[0]


def _player_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_player(
    player: str,
    *,
    home_model: Mapping[str, Any],
    away_model: Mapping[str, Any],
) -> tuple[str, str]:
    needle = _player_key(player)
    hits: list[tuple[str, str]] = []
    for side, model in (("home", home_model), ("away", away_model)):
        if not isinstance(model, Mapping):
            continue
        rows: list[Mapping[str, Any]] = []
        qb = model.get("qb")
        if isinstance(qb, Mapping):
            rows.append(qb)
        skills = model.get("skill_players")
        if isinstance(skills, Sequence) and not isinstance(
            skills, (str, bytes, bytearray)
        ):
            rows.extend(row for row in skills if isinstance(row, Mapping))
        for row in rows:
            canonical = str(row.get("player") or "").strip()
            if not canonical or canonical.endswith("_OTHER"):
                continue
            if _player_key(canonical) == needle:
                hits.append((side, canonical))
    if len(hits) != 1:
        raise ScoreCountPhoneCardError(
            f"PROP_PLAYER_EXACT_MATCH_REQUIRED:{player}:matches={len(hits)}"
        )
    return hits[0]


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
    flags: Mapping[str, bool],
    raw: str,
) -> dict[str, Any]:
    base = {
        "pair_id": pair_id,
        "input_index": int(input_index),
        "side_index": int(side_index),
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
            "reason": engine_row.get("reason")
            or engine_row.get("status")
            or "UNPRICED",
        }

    priced = price_run_it_pick(
        estimate_p=float(engine_row["estimate_p"]),
        push_p=float(engine_row.get("push_p") or 0.0),
        price_american=int(price),
        market_no_vig_p=float(market_no_vig_p),
        qualification_flags=flags,
    )
    price_ok = int(price) >= MAX_STRAIGHT_PRICE
    eligible = (
        priced.ev_per_dollar >= EV_FLOOR
        and priced.edge_probability_points > 0.0
        and price_ok
    )
    if not price_ok:
        reason = "PRICE_ABOVE_STRAIGHT_CEILING"
    elif priced.ev_per_dollar < EV_FLOOR:
        reason = "EV_BELOW_2_PERCENT"
    elif priced.edge_probability_points <= 0.0:
        reason = "NO_POSITIVE_NO_VIG_EDGE"
    else:
        reason = None

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
        "card_eligible": bool(eligible),
        "card_reason": reason,
    }


def _mark_pair_selections(rows: list[dict[str, Any]]) -> None:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault(str(row["pair_id"]), []).append(row)
    for pair in by_pair.values():
        eligible = [
            row
            for row in pair
            if row.get("status") == "PRICED" and row.get("card_eligible")
        ]
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


def _finite_line(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountPhoneCardError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise ScoreCountPhoneCardError(f"{field}:FINITE_REQUIRED")
    return out


def build_score_count_phone_card(
    prediction: Mapping[str, Any],
    ticket: Mapping[str, Any],
    *,
    team_models: Mapping[str, Mapping[str, Any]] | None = None,
    injury_source_ready: bool = False,
    scoring_prior: ScoringCompositionPrior | None = None,
    seed: int = 21,
) -> dict[str, Any]:
    if not isinstance(prediction, Mapping):
        raise ScoreCountPhoneCardError("PREDICTION_OBJECT_REQUIRED")
    if not isinstance(ticket, Mapping):
        raise ScoreCountPhoneCardError("TICKET_OBJECT_REQUIRED")

    observed_at = _utc(ticket.get("observed_at"), "observed_at")
    prediction_at = _utc(prediction.get("prediction_at"), "prediction_at")
    if not prediction_at < observed_at:
        raise ScoreCountPhoneCardError(
            "PREDICTION_MUST_PRECEDE_MARKET_BINDING"
        )

    models = team_models or {}
    games_out: list[dict[str, Any]] = []

    for game_index, raw_game in enumerate(ticket.get("games") or []):
        if not isinstance(raw_game, Mapping):
            raise ScoreCountPhoneCardError("GAME_OBJECT_REQUIRED")
        away = str(raw_game.get("away") or "").strip().upper()
        home = str(raw_game.get("home") or "").strip().upper()
        if not away or not home:
            raise ScoreCountPhoneCardError("GAME_TEAMS_REQUIRED")

        frozen_game = _prediction_game_for_matchup(
            prediction, away=away, home=home
        )
        game_id = str(frozen_game.get("game_id") or "").strip()
        # Reuse the bridge's schema/game identity validation.
        score_count_prediction_game(prediction, game_id)

        model_bundle = models.get(game_id)
        home_model = (
            model_bundle.get("home")
            if isinstance(model_bundle, Mapping)
            else None
        )
        away_model = (
            model_bundle.get("away")
            if isinstance(model_bundle, Mapping)
            else None
        )

        game_requests: list[dict[str, Any]] = []
        game_meta: list[dict[str, Any]] = []
        prop_requests: list[dict[str, Any]] = []
        prop_meta: list[dict[str, Any]] = []

        markets = [
            row
            for row in raw_game.get("markets") or []
            if isinstance(row, Mapping)
        ]
        for input_index, raw in enumerate(markets):
            market = str(raw.get("market") or "").strip().lower()
            no_vig, prices = _decimal_pair(raw)
            pair_id = f"{game_id}:{input_index}:{market}"
            raw_text = str(raw.get("raw") or market)

            if market == "moneyline":
                specs = [
                    ({"market": "moneyline", "selection": "away"}, away, None),
                    ({"market": "moneyline", "selection": "home"}, home, None),
                ]
                for side_index, (request, label, line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": label,
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "spread":
                away_line = _finite_line(raw.get("line"), "spread.line")
                specs = [
                    (
                        {"market": "spread", "selection": "away", "line": away_line},
                        away,
                        away_line,
                    ),
                    (
                        {"market": "spread", "selection": "home", "line": -away_line},
                        home,
                        -away_line,
                    ),
                ]
                for side_index, (request, label, line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": label,
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "total":
                line = _finite_line(raw.get("line"), "total.line")
                specs = [
                    (
                        {"market": "total", "selection": "over", "line": line},
                        "Over",
                        line,
                    ),
                    (
                        {"market": "total", "selection": "under", "line": line},
                        "Under",
                        line,
                    ),
                ]
                for side_index, (request, label, display_line) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": label,
                        "display_line": display_line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            if market == "team_total":
                line = _finite_line(raw.get("line"), "team_total.line")
                team = str(raw.get("team") or "").strip().upper()
                if team not in {away, home}:
                    raise ScoreCountPhoneCardError(
                        f"TEAM_TOTAL_TEAM_NOT_IN_GAME:{team}"
                    )
                side = "home" if team == home else "away"
                specs = [
                    (
                        {
                            "market": "team_total",
                            "team": side,
                            "selection": "over",
                            "line": line,
                        },
                        f"{team} Over",
                    ),
                    (
                        {
                            "market": "team_total",
                            "team": side,
                            "selection": "under",
                            "line": line,
                        },
                        f"{team} Under",
                    ),
                ]
                for side_index, (request, label) in enumerate(specs):
                    game_requests.append(request)
                    game_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": label,
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                    })
                continue

            player = str(raw.get("player") or "").strip()
            if not player:
                raise ScoreCountPhoneCardError(
                    f"UNSUPPORTED_PHONE_MARKET:{market}"
                )
            line = _finite_line(raw.get("line"), "prop.line")
            if not isinstance(home_model, Mapping) or not isinstance(
                away_model, Mapping
            ):
                for side_index, label in enumerate(("Over", "Under")):
                    prop_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": f"{player} {label}",
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                        "market": market,
                        "player": player,
                        "synthetic_no_model_reason": "LIVE_ROLE_MODEL_REQUIRED",
                    })
                continue
            if not injury_source_ready:
                for side_index, label in enumerate(("Over", "Under")):
                    prop_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": f"{player} {label}",
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                        "market": market,
                        "player": player,
                        "synthetic_no_model_reason": "INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS",
                    })
                continue
            try:
                team_side, canonical = _find_player(
                    player,
                    home_model=home_model,
                    away_model=away_model,
                )
            except ScoreCountPhoneCardError as exc:
                for side_index, label in enumerate(("Over", "Under")):
                    prop_meta.append({
                        "pair_id": pair_id,
                        "input_index": input_index,
                        "side_index": side_index,
                        "display_selection": f"{player} {label}",
                        "display_line": line,
                        "price": prices[side_index],
                        "market_no_vig_p": no_vig[side_index],
                        "raw": raw_text,
                        "market": market,
                        "player": player,
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
                prop_meta.append({
                    "pair_id": pair_id,
                    "input_index": input_index,
                    "side_index": side_index,
                    "display_selection": f"{canonical} {selection.title()}",
                    "display_line": line,
                    "price": prices[side_index],
                    "market_no_vig_p": no_vig[side_index],
                    "raw": raw_text,
                })

        game_engine = price_score_count_game_markets(
            prediction,
            game_id=game_id,
            requests=game_requests,
        )
        prop_engine = price_score_count_prop_markets(
            prediction,
            game_id=game_id,
            prop_requests=prop_requests,
            home_model=home_model,
            away_model=away_model,
            scoring_prior=scoring_prior,
            seed=int(seed) + game_index,
        )

        rows: list[dict[str, Any]] = []
        if len(game_engine["game_markets"]) != len(game_meta):
            raise ScoreCountPhoneCardError("GAME_MARKET_RESULT_COUNT_MISMATCH")
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
                flags=_game_flags(),
                raw=meta["raw"],
            ))

        engine_prop_iter = iter(prop_engine["prop_markets"])
        for meta in prop_meta:
            if meta.get("synthetic_no_model_reason"):
                rows.append({
                    "pair_id": meta["pair_id"],
                    "input_index": meta["input_index"],
                    "side_index": meta["side_index"],
                    "market": meta.get("market"),
                    "selection": meta["display_selection"],
                    "line": meta["display_line"],
                    "player": meta.get("player"),
                    "price_american": int(meta["price"]),
                    "market_no_vig_p": float(meta["market_no_vig_p"]),
                    "raw": meta["raw"],
                    "selected": False,
                    "status": "NO_MODEL",
                    "reason": meta["synthetic_no_model_reason"],
                })
                continue
            try:
                engine_row = next(engine_prop_iter)
            except StopIteration as exc:
                raise ScoreCountPhoneCardError(
                    "PROP_MARKET_RESULT_COUNT_MISMATCH"
                ) from exc
            rows.append(_decorate(
                engine_row,
                pair_id=meta["pair_id"],
                input_index=meta["input_index"],
                side_index=meta["side_index"],
                display_selection=meta["display_selection"],
                display_line=meta["display_line"],
                price=meta["price"],
                market_no_vig_p=meta["market_no_vig_p"],
                flags=_prop_flags(injury_ready=injury_source_ready),
                raw=meta["raw"],
            ))
        try:
            next(engine_prop_iter)
            raise ScoreCountPhoneCardError("PROP_MARKET_RESULT_COUNT_MISMATCH")
        except StopIteration:
            pass

        _mark_pair_selections(rows)
        rows.sort(key=lambda row: (int(row["input_index"]), int(row["side_index"])))
        games_out.append({
            "game_id": game_id,
            "away": away,
            "home": home,
            "kickoff_at": frozen_game.get("kickoff_at"),
            "prediction_at": frozen_game.get("prediction_at"),
            "fit_artifact_sha256": prediction.get("fit_artifact_sha256"),
            "prediction_sha256": prediction.get("prediction_sha256"),
            "joint_score_distribution_sha256": frozen_game.get(
                "joint_score_distribution_sha256"
            ),
            "joint_score_td_distribution_sha256": frozen_game.get(
                "joint_score_td_distribution_sha256"
            ),
            "rows": rows,
        })

    all_rows = [row for game in games_out for row in game["rows"]]
    return {
        "schema": SCHEMA,
        "sport": "NFL",
        "observed_at": observed_at.isoformat(),
        "prediction_at": prediction_at.isoformat(),
        "games": games_out,
        "rows": all_rows,
        "selected_rows": [row for row in all_rows if row.get("selected")],
        "pricing_policy": {
            "two_sided_quotes_required": True,
            "ev_floor": EV_FLOOR,
            "straight_price_ceiling": MAX_STRAIGHT_PRICE,
            "score_uses_price_edge_ev": False,
            "prediction_must_precede_market_binding": True,
            "sportsbook_api_required": False,
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
    "ScoreCountPhoneCardError",
    "build_score_count_phone_card",
]
