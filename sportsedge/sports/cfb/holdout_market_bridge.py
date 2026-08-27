"""Strict bridge from CFB walk-forward rows + paired sportsbook prices to HoldoutRunner vectors.

No model fitting, no threshold ownership, and no promotion semantics live here. The bridge
only validates historical price provenance, orients exactly one side per game/market,
and produces the frozen HoldoutRunner input contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Mapping

from .holdout_runner import HoldoutRunner


class CFBHoldoutMarketBridgeError(ValueError):
    pass


MARKETS = ("MONEYLINE", "SPREAD", "TOTAL")
SIDES = {
    "MONEYLINE": ("HOME", "AWAY"),
    "SPREAD": ("HOME", "AWAY"),
    "TOTAL": ("OVER", "UNDER"),
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise CFBHoldoutMarketBridgeError(f"{name}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBHoldoutMarketBridgeError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBHoldoutMarketBridgeError(f"{name}:FINITE_REQUIRED")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise CFBHoldoutMarketBridgeError(f"{name}:PROBABILITY_REQUIRED")
    return out


def _american(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0:
        raise CFBHoldoutMarketBridgeError(f"{name}:NONZERO_INTEGER_AMERICAN_ODDS_REQUIRED")
    return value


def _implied(american: int) -> float:
    return 100.0 / (american + 100.0) if american > 0 else (-american) / ((-american) + 100.0)


def _novig(a: int, b: int) -> tuple[float, float]:
    pa, pb = _implied(a), _implied(b)
    total = pa + pb
    if total <= 0.0:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_PAIR_DEVIG_INVALID")
    return pa / total, pb / total


def _profit_units(american: int, won: bool) -> float:
    if not won:
        return -1.0
    return american / 100.0 if american > 0 else 100.0 / (-american)


def _timestamp(value: Any, name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise CFBHoldoutMarketBridgeError(f"{name}:TIMESTAMP_REQUIRED")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CFBHoldoutMarketBridgeError(f"{name}:ISO8601_REQUIRED") from exc


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CFBHoldoutMarketBridgeError(f"{name}:INTEGER_REQUIRED")
    return value


@dataclass(frozen=True)
class OrientedRow:
    game_id: str
    season: int
    market: str
    side: str
    y_true: int
    model_prob: float
    decision_novig_prob: float
    clv: float
    roi: float


def _normalize_prediction(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBHoldoutMarketBridgeError("CFB_PREDICTION_ROW_OBJECT_REQUIRED")
    game_id = str(raw.get("game_id") or "").strip()
    if not game_id:
        raise CFBHoldoutMarketBridgeError("CFB_GAME_ID_REQUIRED")
    season = _int(raw.get("season"), "season")
    home_score = _finite(raw.get("home_score"), "home_score")
    away_score = _finite(raw.get("away_score"), "away_score")
    if home_score < 0 or away_score < 0:
        raise CFBHoldoutMarketBridgeError("CFB_NEGATIVE_REALIZED_SCORE")
    home_win_p = _prob(raw.get("home_win_p"), "home_win_p")
    home_spread = _finite(raw.get("home_team_spread"), "home_team_spread")
    total_line = _finite(raw.get("over_under"), "over_under")
    spread_home = _prob(raw.get("spread_home_cover_p"), "spread_home_cover_p")
    spread_push = _prob(raw.get("spread_push_p"), "spread_push_p")
    total_over = _prob(raw.get("total_over_p"), "total_over_p")
    total_push = _prob(raw.get("total_push_p"), "total_push_p")
    if spread_home + spread_push > 1.0 + 1e-12:
        raise CFBHoldoutMarketBridgeError("CFB_SPREAD_PROBABILITY_MASS_INVALID")
    if total_over + total_push > 1.0 + 1e-12:
        raise CFBHoldoutMarketBridgeError("CFB_TOTAL_PROBABILITY_MASS_INVALID")
    return {
        "game_id": game_id,
        "season": season,
        "home_score": home_score,
        "away_score": away_score,
        "home_win_p": home_win_p,
        "home_team_spread": home_spread,
        "over_under": total_line,
        "spread_home_cover_p": spread_home,
        "spread_push_p": spread_push,
        "total_over_p": total_over,
        "total_push_p": total_push,
    }


def _normalize_price(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_ROW_OBJECT_REQUIRED")
    game_id = str(raw.get("game_id") or "").strip()
    market = str(raw.get("market") or "").strip().upper()
    if not game_id:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_GAME_ID_REQUIRED")
    if market not in MARKETS:
        raise CFBHoldoutMarketBridgeError(f"CFB_PRICE_MARKET_UNSUPPORTED:{market or 'MISSING'}")
    sportsbook = str(raw.get("sportsbook") or "").strip()
    if not sportsbook:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_SPORTSBOOK_REQUIRED")
    decision_time = _timestamp(raw.get("decision_time"), "decision_time")
    close_time = _timestamp(raw.get("close_time"), "close_time")
    game_start_time = _timestamp(raw.get("game_start_time"), "game_start_time")
    if not decision_time < close_time < game_start_time:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_TIME_ORDER_INVALID")
    a_side, b_side = SIDES[market]
    if str(raw.get("side_a") or "").strip().upper() != a_side:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_SIDE_A_IDENTITY_MISMATCH")
    if str(raw.get("side_b") or "").strip().upper() != b_side:
        raise CFBHoldoutMarketBridgeError("CFB_PRICE_SIDE_B_IDENTITY_MISMATCH")
    decision_a = _american(raw.get("decision_a_american"), "decision_a_american")
    decision_b = _american(raw.get("decision_b_american"), "decision_b_american")
    close_a = _american(raw.get("close_a_american"), "close_a_american")
    close_b = _american(raw.get("close_b_american"), "close_b_american")
    threshold = raw.get("threshold")
    if market == "MONEYLINE":
        if threshold not in (None, ""):
            raise CFBHoldoutMarketBridgeError("CFB_MONEYLINE_THRESHOLD_FORBIDDEN")
        threshold_value = None
    else:
        threshold_value = _finite(threshold, "threshold")
    return {
        "game_id": game_id,
        "market": market,
        "sportsbook": sportsbook,
        "decision_time": decision_time,
        "close_time": close_time,
        "game_start_time": game_start_time,
        "threshold": threshold_value,
        "decision_a": decision_a,
        "decision_b": decision_b,
        "close_a": close_a,
        "close_b": close_b,
    }


def _model_pair(row: Mapping[str, Any], market: str) -> tuple[float, float]:
    if market == "MONEYLINE":
        p = row["home_win_p"]
    elif market == "SPREAD":
        non_push = 1.0 - row["spread_push_p"]
        if non_push <= 1e-15:
            raise CFBHoldoutMarketBridgeError("CFB_SPREAD_SETTLED_SAMPLE_SPACE_EMPTY")
        p = row["spread_home_cover_p"] / non_push
    else:
        non_push = 1.0 - row["total_push_p"]
        if non_push <= 1e-15:
            raise CFBHoldoutMarketBridgeError("CFB_TOTAL_SETTLED_SAMPLE_SPACE_EMPTY")
        p = row["total_over_p"] / non_push
    if not 0.0 <= p <= 1.0:
        raise CFBHoldoutMarketBridgeError("CFB_ORIENTED_MODEL_PROBABILITY_INVALID")
    return p, 1.0 - p


def _settlement(row: Mapping[str, Any], market: str) -> tuple[int | None, int | None]:
    hs, aas = row["home_score"], row["away_score"]
    if market == "MONEYLINE":
        if abs(hs - aas) <= 1e-12:
            raise CFBHoldoutMarketBridgeError("CFB_FINAL_SCORE_TIE_INVALID")
        home = 1 if hs > aas else 0
        return home, 1 - home
    if market == "SPREAD":
        value = (hs - aas) + row["home_team_spread"]
    else:
        value = (hs + aas) - row["over_under"]
    if abs(value) <= 1e-12:
        return None, None
    first = 1 if value > 0 else 0
    return first, 1 - first


def _threshold_matches(pred: Mapping[str, Any], price: Mapping[str, Any]) -> bool:
    market = price["market"]
    if market == "MONEYLINE":
        return True
    expected = pred["home_team_spread"] if market == "SPREAD" else pred["over_under"]
    return abs(float(price["threshold"]) - float(expected)) <= 1e-12


def orient_one(pred: Mapping[str, Any], price: Mapping[str, Any]) -> OrientedRow | None:
    market = price["market"]
    if pred["game_id"] != price["game_id"]:
        raise CFBHoldoutMarketBridgeError("CFB_GAME_IDENTITY_MISMATCH")
    if not _threshold_matches(pred, price):
        raise CFBHoldoutMarketBridgeError("CFB_ORIGINAL_THRESHOLD_PRICE_REQUIRED")
    model_a, model_b = _model_pair(pred, market)
    dec_a, dec_b = _novig(price["decision_a"], price["decision_b"])
    close_a, close_b = _novig(price["close_a"], price["close_b"])
    y_a, y_b = _settlement(pred, market)
    if y_a is None:
        return None
    edge_a, edge_b = model_a - dec_a, model_b - dec_b
    choose_a = edge_a >= edge_b
    if choose_a:
        side, y, model_p, dec_p, close_p, odds = (
            SIDES[market][0], y_a, model_a, dec_a, close_a, price["decision_a"]
        )
    else:
        side, y, model_p, dec_p, close_p, odds = (
            SIDES[market][1], y_b, model_b, dec_b, close_b, price["decision_b"]
        )
    return OrientedRow(
        game_id=pred["game_id"],
        season=pred["season"],
        market=market,
        side=side,
        y_true=int(y),
        model_prob=float(model_p),
        decision_novig_prob=float(dec_p),
        clv=float(close_p - dec_p),
        roi=float(_profit_units(odds, bool(y))),
    )


def build_full_card_inputs(
    prediction_rows: Iterable[Mapping[str, Any]],
    price_rows: Iterable[Mapping[str, Any]],
    *,
    pit_reproducible: bool,
    leakage_violations: int,
    recent_two_season_ok: bool,
) -> dict[str, dict[str, Any]]:
    if type(pit_reproducible) is not bool or type(recent_two_season_ok) is not bool:
        raise CFBHoldoutMarketBridgeError("CFB_EVIDENCE_BOOL_REQUIRED")
    if isinstance(leakage_violations, bool) or not isinstance(leakage_violations, int) or leakage_violations < 0:
        raise CFBHoldoutMarketBridgeError("CFB_LEAKAGE_NONNEGATIVE_INTEGER_REQUIRED")
    predictions = [_normalize_prediction(row) for row in prediction_rows]
    if not predictions:
        raise CFBHoldoutMarketBridgeError("CFB_PREDICTION_ROWS_REQUIRED")
    pred_by_id = {row["game_id"]: row for row in predictions}
    if len(pred_by_id) != len(predictions):
        raise CFBHoldoutMarketBridgeError("CFB_PREDICTION_GAME_ID_DUPLICATE")
    prices = [_normalize_price(row) for row in price_rows]
    price_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in prices:
        key = (row["game_id"], row["market"])
        if key in price_by_key:
            raise CFBHoldoutMarketBridgeError("CFB_PAIRED_PRICE_DUPLICATE")
        price_by_key[key] = row
    expected = {(game_id, market) for game_id in pred_by_id for market in MARKETS}
    supplied = set(price_by_key)
    if supplied != expected:
        missing = sorted(expected - supplied)
        extra = sorted(supplied - expected)
        raise CFBHoldoutMarketBridgeError(
            "CFB_PAIRED_PRICE_SURFACE_MISMATCH:"
            f"missing={missing!r}:extra={extra!r}"
        )
    out: dict[str, dict[str, Any]] = {}
    for market in MARKETS:
        oriented: list[OrientedRow] = []
        for game_id in sorted(pred_by_id):
            row = orient_one(pred_by_id[game_id], price_by_key[(game_id, market)])
            if row is not None:
                oriented.append(row)
        if not oriented:
            raise CFBHoldoutMarketBridgeError(f"CFB_{market}_SETTLED_ROWS_REQUIRED")
        out[market] = {
            "y_true": [row.y_true for row in oriented],
            "y_prob": [row.model_prob for row in oriented],
            "market_novig_prob": [row.decision_novig_prob for row in oriented],
            "clv_series": [row.clv for row in oriented],
            "roi_series": [row.roi for row in oriented],
            "season_ids": [row.season for row in oriented],
            "pit_reproducible": pit_reproducible,
            "leakage_violations": leakage_violations,
            "paired_historical_price_evidence_complete": True,
            "recent_two_season_ok": recent_two_season_ok,
        }
    return out


def run_bridge(
    prediction_rows: Iterable[Mapping[str, Any]],
    price_rows: Iterable[Mapping[str, Any]],
    *,
    pit_reproducible: bool,
    leakage_violations: int,
    recent_two_season_ok: bool,
    policy_path: str = "config/cfb_truth_gate_v1.json",
):
    runner = HoldoutRunner(policy_path)
    inputs = build_full_card_inputs(
        prediction_rows,
        price_rows,
        pit_reproducible=pit_reproducible,
        leakage_violations=leakage_violations,
        recent_two_season_ok=recent_two_season_ok,
    )
    return runner.run_full_card(inputs)
