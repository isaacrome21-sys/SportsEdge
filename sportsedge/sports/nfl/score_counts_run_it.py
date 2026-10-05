"""Operational RUN IT adapter for NFL_SCORE_COUNTS_G1.

The score-count prediction owns the joint game-score distribution. Sportsbook
quotes are bound only after that distribution exists. Existing NFL boards retain
ownership of paired-price devig, EV, Score-B, quote hygiene, and player-prop
execution rules.

Research-only. No Truth Gate, promotion, staking, OFFICIAL, or Model_P authority.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.nfl_prop_run_it_score_b import run_prop_board
from sportsedge.nfl_run_it import MAX_QUOTE_SKEW_SECONDS, QUOTE_TTL_SECONDS
from sportsedge.nfl_run_it_score_binding import score_b_by_identity
from sportsedge.nfl_run_it_scored import run_it_scored
from sportsedge.nfl_run_it_scoring import price_run_it_pick
from sportsedge.nfl_td_run_it_score_b import run_td_board
from sportsedge.sports.nfl.score_counts_market_bridge import (
    price_score_count_game_markets,
    score_count_paths,
    score_count_prediction_game,
)
from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_props_from_paths,
)
from sportsedge.sports.nfl.unified_run_it import (
    _game_estimates,
    _game_requests,
    _ordinary_prop_estimates,
    _player_side_index,
    _prop_requests,
    _td_estimates,
    _td_requests,
)
from sportsedge.truth_gate import american_to_decimal

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_RUN_IT_V1"
TEAM_TOTAL_MARKET = "team_total"
MAX_STRAIGHT_PRICE = -165
EV_FLOOR = 0.02


class ScoreCountRunItError(ValueError):
    pass


def _text(value: Any, field: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ScoreCountRunItError(f"{field}:REQUIRED")
    return out


def _ts(value: Any, field: str) -> datetime:
    try:
        out = parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise ScoreCountRunItError(f"{field}:INVALID") from exc
    return out


def _american(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountRunItError("TEAM_TOTAL_PRICE_INVALID") from exc
    if not isfinite(number) or number != int(number) or -100 < number < 100:
        raise ScoreCountRunItError("TEAM_TOTAL_PRICE_INVALID")
    return int(number)


def _line(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountRunItError("TEAM_TOTAL_LINE_INVALID") from exc
    if not isfinite(number) or number < 0:
        raise ScoreCountRunItError("TEAM_TOTAL_LINE_INVALID")
    return number


def _team_side(value: Any, *, home_team: str, away_team: str) -> tuple[str, str]:
    raw = _text(value, "team_total.team")
    low = raw.lower()
    if low == "home" or raw.upper() == home_team.upper():
        return "home", home_team
    if low == "away" or raw.upper() == away_team.upper():
        return "away", away_team
    raise ScoreCountRunItError(f"TEAM_TOTAL_TEAM_INVALID:{raw}")


def team_total_qualification_selection(team: str, selection: str) -> str:
    side = str(selection or "").strip().upper()
    if side not in {"OVER", "UNDER"}:
        raise ScoreCountRunItError("TEAM_TOTAL_SELECTION_INVALID")
    return f"{_text(team, 'team_total.team_name')}:{side}"


def _normalize_team_total_quote(
    raw: Mapping[str, Any],
    *,
    game_id: str,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ScoreCountRunItError("TEAM_TOTAL_QUOTE_OBJECT_REQUIRED")
    if _text(raw.get("game_id"), "team_total.game_id") != str(game_id):
        raise ScoreCountRunItError("TEAM_TOTAL_GAME_IDENTITY_MISMATCH")
    market = str(raw.get("market") or "").strip().lower()
    if market not in {"team_total", "team_totals"}:
        raise ScoreCountRunItError("TEAM_TOTAL_MARKET_REQUIRED")
    side, team = _team_side(raw.get("team"), home_team=home_team, away_team=away_team)
    selection = _text(raw.get("selection"), "team_total.selection").upper()
    if selection not in {"OVER", "UNDER"}:
        raise ScoreCountRunItError("TEAM_TOTAL_SELECTION_INVALID")
    book = str(raw.get("book") or raw.get("book_key") or "").strip().lower()
    if not book:
        raise ScoreCountRunItError("TEAM_TOTAL_BOOK_REQUIRED")
    retrieved = _ts(raw.get("retrieved_at"), "team_total.retrieved_at")
    return {
        "game_id": str(game_id),
        "market": TEAM_TOTAL_MARKET,
        "team_side": side,
        "team": team,
        "selection": selection,
        "line": _line(raw.get("line")),
        "price_american": _american(raw.get("price_american", raw.get("american_odds"))),
        "book": book,
        "retrieved_at": retrieved,
    }


def _team_total_pair_key(row: Mapping[str, Any]) -> tuple[str, str, str, float]:
    return (
        str(row["game_id"]),
        str(row["team_side"]),
        str(row["book"]),
        round(float(row["line"]), 4),
    )


def _team_total_board(
    *,
    model_rows: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    game_id: str,
    home_team: str,
    away_team: str,
    qualification_snapshots: Sequence[Mapping[str, Any]],
    as_of: Any,
    edge_floor: float,
) -> list[dict[str, Any]]:
    if not quotes:
        return []
    try:
        floor = float(edge_floor)
    except (TypeError, ValueError) as exc:
        raise ScoreCountRunItError("EDGE_FLOOR_INVALID") from exc
    if not isfinite(floor) or floor < 0:
        raise ScoreCountRunItError("EDGE_FLOOR_INVALID")

    now = _ts(as_of, "as_of")
    norm = [
        _normalize_team_total_quote(
            row, game_id=game_id, home_team=home_team, away_team=away_team
        )
        for row in quotes
    ]
    model_map: dict[tuple[str, str, float], Mapping[str, Any]] = {}
    for row in model_rows:
        key = (
            str(row.get("team") or "").strip().lower(),
            str(row.get("selection") or "").strip().upper(),
            round(float(row.get("line")), 4),
        )
        if key in model_map:
            raise ScoreCountRunItError(f"TEAM_TOTAL_MODEL_DUPLICATE:{key}")
        model_map[key] = row

    scores = score_b_by_identity(qualification_snapshots)
    rows: list[dict[str, Any]] = []
    for quote in norm:
        base = {
            "game_id": quote["game_id"],
            "market": TEAM_TOTAL_MARKET,
            "team": quote["team"],
            "team_side": quote["team_side"],
            "selection": quote["selection"],
            "line": quote["line"],
            "book": quote["book"],
            "price_american": quote["price_american"],
            "retrieved_at": quote["retrieved_at"].isoformat().replace("+00:00", "Z"),
            "selected": False,
        }
        age = (now - quote["retrieved_at"]).total_seconds()
        if age > QUOTE_TTL_SECONDS or age < -MAX_QUOTE_SKEW_SECONDS:
            rows.append({**base, "status": "BLOCKED", "block_reason": "QUOTE_TIME_INVALID"})
            continue

        opposites = [
            other for other in norm
            if other is not quote
            and _team_total_pair_key(other) == _team_total_pair_key(quote)
            and other["selection"] != quote["selection"]
        ]
        if len(opposites) != 1:
            rows.append({**base, "status": "BLOCKED", "block_reason": "PAIRED_PRICE_REQUIRED"})
            continue
        opposite = opposites[0]
        if abs((quote["retrieved_at"] - opposite["retrieved_at"]).total_seconds()) > MAX_QUOTE_SKEW_SECONDS:
            rows.append({**base, "status": "BLOCKED", "block_reason": "PAIRED_QUOTE_TIME_SKEW"})
            continue

        model_key = (
            quote["team_side"],
            quote["selection"],
            round(float(quote["line"]), 4),
        )
        model = model_map.get(model_key)
        if model is None or model.get("status") != "PRICED_RESEARCH":
            rows.append({
                **base,
                "status": "BLOCKED",
                "block_reason": (
                    str((model or {}).get("reason") or "TEAM_TOTAL_MODEL_ESTIMATE_REQUIRED")
                ),
            })
            continue

        q_selection = team_total_qualification_selection(
            quote["team"], quote["selection"]
        )
        score_key = (str(game_id), TEAM_TOTAL_MARKET, q_selection)
        if score_key not in scores:
            rows.append({
                **base,
                "status": "BLOCKED",
                "block_reason": "BLOCKED_MISSING_QUALIFICATION",
            })
            continue

        try:
            no_vig = float(devig(
                [
                    american_to_decimal(quote["price_american"]),
                    american_to_decimal(opposite["price_american"]),
                ],
                trigger_american=400,
                max_spread_pp=1.0,
            )[0])
            priced = price_run_it_pick(
                estimate_p=float(model["estimate_p"]),
                push_p=float(model.get("push_p") or 0.0),
                price_american=int(quote["price_american"]),
                market_no_vig_p=no_vig,
            )
        except Exception as exc:
            rows.append({
                **base,
                "status": "BLOCKED",
                "block_reason": f"TEAM_TOTAL_PRICE_FAILED:{exc}",
            })
            continue

        cap_ok = int(quote["price_american"]) >= MAX_STRAIGHT_PRICE
        ev_ok = float(priced.ev_per_dollar) >= EV_FLOOR
        edge_ok = float(priced.edge_probability_points) > floor
        reason = None
        if not cap_ok:
            reason = "PRICE_ABOVE_STRAIGHT_CEILING"
        elif not ev_ok:
            reason = "EV_BELOW_2_PERCENT"
        elif not edge_ok:
            reason = "EDGE_BELOW_FLOOR"

        rows.append({
            **base,
            "status": "PRICED",
            "block_reason": None,
            "estimate_p": float(priced.estimate_p),
            "push_p": float(priced.push_p),
            "loss_p": float(priced.loss_p),
            "conditional_win_probability": float(priced.fair_probability),
            "fair_american": int(priced.fair_american),
            "market_no_vig_p": float(priced.market_no_vig_p),
            "edge_probability_points": float(priced.edge_probability_points),
            "ev_per_dollar": float(priced.ev_per_dollar),
            "score_0_100": int(scores[score_key]),
            "selected": bool(cap_ok and ev_ok and edge_ok),
            "card_reason": reason,
        })

    rows.sort(key=lambda row: (
        not bool(row.get("selected")),
        -float(row.get("ev_per_dollar") or -999.0),
        str(row.get("team")),
        str(row.get("selection")),
    ))
    rank = 0
    for row in rows:
        if row.get("selected"):
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = None
    return rows


def _straight_selected(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        if row.get("status") not in {"OK", "PRICED"}:
            continue
        price = row.get("price_american")
        ev = row.get("ev_per_dollar")
        edge = row.get("edge_probability_points")
        if price is None or ev is None or edge is None:
            continue
        if int(price) < MAX_STRAIGHT_PRICE:
            continue
        if float(ev) < EV_FLOOR or float(edge) <= 0.0:
            continue
        selected.append(row)
    selected.sort(key=lambda row: (
        -float(row["ev_per_dollar"]),
        -float(row["edge_probability_points"]),
        str(row.get("game_id")),
        str(row.get("market")),
        str(row.get("selection") or row.get("player")),
    ))
    for i, row in enumerate(selected, 1):
        row["card_rank"] = i
    return selected


def _capped_game_card(card: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(card)
    picks = []
    blocked = []
    for raw in card.get("picks") or []:
        row = dict(raw)
        if int(row["price_american"]) < MAX_STRAIGHT_PRICE:
            blocked.append({**row, "card_reason": "PRICE_ABOVE_STRAIGHT_CEILING"})
            continue
        if float(row.get("ev_per_dollar") or 0.0) < EV_FLOOR:
            blocked.append({**row, "card_reason": "EV_BELOW_2_PERCENT"})
            continue
        picks.append(row)
    for i, row in enumerate(picks, 1):
        row["rank"] = i
    out["picks"] = picks
    out["price_or_ev_blocked"] = blocked
    out["max_straight_price"] = MAX_STRAIGHT_PRICE
    out["ev_floor"] = EV_FLOOR
    return out


def run_score_count_nfl_run_it(
    *,
    prediction: Mapping[str, Any],
    game_id: str,
    home_team: str,
    away_team: str,
    game_quotes: Sequence[Mapping[str, Any]] = (),
    team_total_quotes: Sequence[Mapping[str, Any]] = (),
    prop_quotes: Sequence[Mapping[str, Any]] = (),
    td_quotes: Sequence[Mapping[str, Any]] = (),
    qualification_snapshots: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any = None,
    as_of: Any,
    edge_floor: float = 0.02,
    executable_book: str = "draftkings",
    seed: int = 21,
) -> dict[str, Any]:
    """Price one game's complete score-count card from one shared 50k score state."""
    game_id = _text(game_id, "game_id")
    home_team = _text(home_team, "home_team")
    away_team = _text(away_team, "away_team")

    game = score_count_prediction_game(prediction, game_id)
    paths = score_count_paths(game)

    game_requests = _game_requests(
        game_quotes, home_team=home_team, away_team=away_team
    )
    game_model = price_score_count_game_markets(
        prediction, game_id=game_id, requests=game_requests
    )
    game_estimates = _game_estimates(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        rows=game_model["game_markets"],
    )
    game_card = run_it_scored(
        game_quotes,
        game_estimates,
        qualification_snapshots,
        simulations={game_id: paths},
        as_of=as_of,
        edge_floor=edge_floor,
    ).to_dict() if game_quotes else {
        "schema": "SPORTSEDGE_NFL_RUN_IT_CARD_V2",
        "sport": "nfl",
        "picks": [],
        "omitted": 0,
        "empty_reason": "No game quotes supplied.",
        "authority_footer": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }
    game_card = _capped_game_card(game_card)

    tt_requests: list[dict[str, Any]] = []
    seen_tt: set[tuple[str, str, float]] = set()
    for raw in team_total_quotes:
        q = _normalize_team_total_quote(
            raw, game_id=game_id, home_team=home_team, away_team=away_team
        )
        key = (q["team_side"], q["selection"], round(float(q["line"]), 4))
        if key not in seen_tt:
            seen_tt.add(key)
            tt_requests.append({
                "market": TEAM_TOTAL_MARKET,
                "team": q["team_side"],
                "selection": q["selection"].lower(),
                "line": q["line"],
            })
    tt_model = price_score_count_game_markets(
        prediction, game_id=game_id, requests=tt_requests
    ) if tt_requests else {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_MARKET_BRIDGE_V1",
        "game_markets": [],
    }
    team_total_board = _team_total_board(
        model_rows=tt_model["game_markets"],
        quotes=team_total_quotes,
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        qualification_snapshots=qualification_snapshots,
        as_of=as_of,
        edge_floor=edge_floor,
    )

    player_sides = _player_side_index(home_model, away_model)
    prop_requests = _prop_requests(
        prop_quotes,
        player_sides=player_sides,
        home_team=home_team,
        away_team=away_team,
    )
    td_requests = _td_requests(
        td_quotes,
        player_sides=player_sides,
        home_team=home_team,
        away_team=away_team,
    )
    prop_model = price_score_count_props_from_paths(
        game_id=game_id,
        score_paths=paths,
        prop_requests=[*prop_requests, *td_requests],
        home_model=home_model,
        away_model=away_model,
        scoring_prior=scoring_prior,
        seed=seed,
    ) if prop_requests or td_requests else {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_PROP_BRIDGE_V1",
        "game_id": game_id,
        "score_path_count": len(paths),
        "prop_markets": [],
    }

    prop_estimates, prop_blocks = _ordinary_prop_estimates(
        game_id=game_id, rows=prop_model["prop_markets"]
    )
    prop_board = [
        asdict(row) for row in run_prop_board(
            estimates=prop_estimates,
            quotes=prop_quotes,
            qualification_snapshots=qualification_snapshots,
            as_of=as_of,
            executable_book=executable_book,
        )
    ] if prop_quotes and prop_estimates else []

    td_estimates, td_blocks = _td_estimates(
        game_id=game_id, rows=prop_model["prop_markets"]
    )
    td_board = [
        asdict(row) for row in run_td_board(
            estimates=td_estimates,
            quotes=td_quotes,
            qualification_snapshots=qualification_snapshots,
            as_of=as_of,
            executable_book=executable_book,
        )
    ] if td_quotes and td_estimates else []

    selected = [
        *[{"surface": "game", **row} for row in game_card.get("picks") or []],
        *[{"surface": "team_total", **row} for row in team_total_board if row.get("selected")],
        *[{"surface": "prop", **row} for row in _straight_selected(prop_board)],
        *[{"surface": "td", **row} for row in _straight_selected(td_board)],
    ]
    selected.sort(key=lambda row: (
        -float(row.get("ev_per_dollar") or -999.0),
        -float(row.get("edge_probability_points") or -999.0),
        str(row.get("surface")),
        str(row.get("market") or ""),
    ))
    for i, row in enumerate(selected, 1):
        row["card_rank"] = i

    return {
        "schema": SCHEMA,
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "game_id": game_id,
        "home": home_team,
        "away": away_team,
        "fit_artifact_sha256": prediction.get("fit_artifact_sha256"),
        "prediction_sha256": prediction.get("prediction_sha256"),
        "joint_score_distribution_sha256": game.get("joint_score_distribution_sha256"),
        "score_path_count": len(paths),
        "game_model": game_model,
        "game_card": game_card,
        "team_total_model": tt_model,
        "team_total_board": team_total_board,
        "prop_model": prop_model,
        "prop_board": prop_board,
        "td_board": td_board,
        "model_blocks": [*prop_blocks, *td_blocks],
        "selected_card": selected,
        "straight_price_ceiling": MAX_STRAIGHT_PRICE,
        "ev_floor": EV_FLOOR,
        "market_data_used_to_create_score_distribution": False,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": True,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


__all__ = [
    "SCHEMA",
    "EV_FLOOR",
    "MAX_STRAIGHT_PRICE",
    "ScoreCountRunItError",
    "run_score_count_nfl_run_it",
    "team_total_qualification_selection",
]
