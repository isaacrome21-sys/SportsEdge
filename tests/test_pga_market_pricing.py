from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.pga.live_card import CandidateMarket, evaluate_live_card
from sportsedge.pga.market_pricing import (
    american_to_implied,
    expected_value_per_unit,
    full_field_no_vig,
    probability_to_american,
    two_way_no_vig,
)


def test_american_probability_round_trip():
    p = american_to_implied(-150)
    assert p == pytest.approx(0.60)
    assert probability_to_american(p) == pytest.approx(-150.0)


def test_two_way_no_vig_sums_to_one():
    a, b = two_way_no_vig(-110, -110)
    assert a == pytest.approx(0.5)
    assert b == pytest.approx(0.5)


def test_full_field_no_vig_normalizes_outright_board():
    probs = full_field_no_vig({"A": +200, "B": +300, "C": +400})
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs["A"] > probs["B"] > probs["C"]


def test_positive_ev_calculation():
    # 60% model probability at even money = +20% expected net return.
    assert expected_value_per_unit(0.60, +100) == pytest.approx(0.20)


def test_live_card_promotes_only_when_price_and_freshness_pass():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    candidate = CandidateMarket(
        market="R2 score",
        selection="Player over 68.5",
        offered_american=-110,
        model_probability=0.60,
        market_probability=0.50,
        min_edge=0.04,
        min_ev=0.03,
    )
    decision = evaluate_live_card(
        [candidate],
        leaderboard_timestamp=now - timedelta(minutes=2),
        tee_time_timestamp=now - timedelta(hours=2),
        weather_timestamp=now - timedelta(minutes=20),
        market_timestamp=now - timedelta(minutes=3),
        has_shot_level_data=True,
        wd_status_verified=True,
        market_rules_verified=True,
        now=now,
    )[0]
    assert decision.status == "OFFICIAL"
    assert decision.price.edge == pytest.approx(0.10)
    assert decision.price.expected_value > 0.0


def test_live_card_blocks_stale_market_even_with_edge():
    now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    candidate = CandidateMarket(
        market="R2 score",
        selection="Player over 68.5",
        offered_american=+100,
        model_probability=0.65,
        market_probability=0.50,
        min_edge=0.04,
        min_ev=0.03,
    )
    decision = evaluate_live_card(
        [candidate],
        leaderboard_timestamp=now - timedelta(minutes=2),
        tee_time_timestamp=now - timedelta(hours=2),
        weather_timestamp=now - timedelta(minutes=20),
        market_timestamp=now - timedelta(minutes=30),
        has_shot_level_data=True,
        wd_status_verified=True,
        market_rules_verified=True,
        now=now,
    )[0]
    assert decision.status == "NO_BET"
    assert any(reason.startswith("stale_market") for reason in decision.gate.reasons)
