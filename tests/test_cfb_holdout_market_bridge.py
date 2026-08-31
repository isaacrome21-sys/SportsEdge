from __future__ import annotations

import pytest

from sportsedge.sports.cfb.holdout_market_bridge import (
    CFBHoldoutMarketBridgeError,
    build_full_card_inputs,
)


def pred(game_id="g1", season=2022, **changes):
    row = dict(
        game_id=game_id,
        season=season,
        home_score=31,
        away_score=24,
        home_win_p=0.62,
        home_team_spread=-3.0,
        over_under=52.5,
        spread_home_cover_p=0.60,
        spread_push_p=0.0,
        total_over_p=0.40,
        total_push_p=0.0,
    )
    row.update(changes)
    return row


def price(game_id, market, *, threshold=None, **changes):
    sides = {
        "MONEYLINE": ("HOME", "AWAY"),
        "SPREAD": ("HOME", "AWAY"),
        "TOTAL": ("OVER", "UNDER"),
    }[market]
    row = dict(
        game_id=game_id,
        market=market,
        sportsbook="DK",
        decision_time="2026-08-27T12:00:00+00:00",
        close_time="2026-08-27T15:00:00+00:00",
        game_start_time="2026-08-27T17:00:00+00:00",
        side_a=sides[0],
        side_b=sides[1],
        threshold=threshold,
        decision_a_american=-110,
        decision_b_american=-110,
        close_a_american=-125,
        close_b_american=105,
    )
    row.update(changes)
    return row


def full_prices(game_id="g1"):
    return [
        price(game_id, "MONEYLINE"),
        price(game_id, "SPREAD", threshold=-3.0),
        price(game_id, "TOTAL", threshold=52.5),
    ]


def build(predictions, prices):
    return build_full_card_inputs(
        predictions,
        prices,
        pit_reproducible=True,
        leakage_violations=0,
        recent_two_season_ok=True,
    )


def test_exact_three_market_surface_and_one_orientation_per_game():
    out = build([pred()], full_prices())
    assert set(out) == {"MONEYLINE", "SPREAD", "TOTAL"}
    assert len(out["MONEYLINE"]["y_true"]) == 1
    assert len(out["SPREAD"]["y_true"]) == 1
    assert len(out["TOTAL"]["y_true"]) == 1
    assert out["MONEYLINE"]["y_prob"][0] == pytest.approx(0.62)
    assert out["SPREAD"]["y_prob"][0] == pytest.approx(0.60)
    assert out["TOTAL"]["y_prob"][0] == pytest.approx(0.60)  # under selected


def test_away_and_under_can_be_selected_not_home_over_only():
    row = pred(home_win_p=0.35, spread_home_cover_p=0.35, total_over_p=0.35)
    out = build([row], full_prices())
    assert out["MONEYLINE"]["y_prob"][0] == pytest.approx(0.65)
    assert out["SPREAD"]["y_prob"][0] == pytest.approx(0.65)
    assert out["TOTAL"]["y_prob"][0] == pytest.approx(0.65)


def test_missing_paired_price_fails_closed():
    with pytest.raises(CFBHoldoutMarketBridgeError, match="PAIRED_PRICE_SURFACE_MISMATCH"):
        build([pred()], full_prices()[:-1])


def test_duplicate_price_pair_fails_closed():
    prices = full_prices()
    prices.append(price("g1", "MONEYLINE"))
    with pytest.raises(CFBHoldoutMarketBridgeError, match="PAIRED_PRICE_DUPLICATE"):
        build([pred()], prices)


def test_original_threshold_is_required_for_spread_and_total():
    prices = full_prices()
    prices[1] = price("g1", "SPREAD", threshold=-2.5)
    with pytest.raises(CFBHoldoutMarketBridgeError, match="ORIGINAL_THRESHOLD_PRICE_REQUIRED"):
        build([pred()], prices)


def test_decision_close_start_order_is_strict():
    prices = full_prices()
    prices[0] = price(
        "g1",
        "MONEYLINE",
        close_time="2026-08-27T11:00:00+00:00",
    )
    with pytest.raises(CFBHoldoutMarketBridgeError, match="PRICE_TIME_ORDER_INVALID"):
        build([pred()], prices)


def test_spread_and_total_pushes_are_excluded_from_scoring_vectors():
    row = pred(home_score=28, away_score=25, home_team_spread=-3.0, over_under=53.0)
    prices = [
        price("g1", "MONEYLINE"),
        price("g1", "SPREAD", threshold=-3.0),
        price("g1", "TOTAL", threshold=53.0),
    ]
    with pytest.raises(CFBHoldoutMarketBridgeError, match="SPREAD_SETTLED_ROWS_REQUIRED"):
        build([row], prices)


def test_clv_is_close_minus_decision_novig_for_selected_side():
    out = build([pred()], full_prices())
    # HOME/SPREAD selected; -125/105 no-vig should move toward HOME from 50%.
    assert out["SPREAD"]["clv_series"][0] > 0.0


def test_roi_uses_actual_decision_price_after_orientation():
    prices = full_prices()
    prices[0] = price(
        "g1",
        "MONEYLINE",
        decision_a_american=120,
        decision_b_american=-140,
        close_a_american=110,
        close_b_american=-130,
    )
    out = build([pred(home_win_p=0.70)], prices)
    assert out["MONEYLINE"]["roi_series"][0] == pytest.approx(1.20)


def test_no_threshold_or_promotion_number_is_owned_by_bridge():
    out = build([pred()], full_prices())
    for market in out.values():
        assert "edge_floor" not in market
        assert market["paired_historical_price_evidence_complete"] is True
