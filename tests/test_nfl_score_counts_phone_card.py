from __future__ import annotations

import copy

import pytest

from sportsedge.nfl_lines_intake import parse_nfl_lines, tickets_to_dict
from sportsedge.sports.nfl.score_counts_artifact import PREDICTION_SCHEMA
from sportsedge.sports.nfl.score_counts_phone_card import (
    ScoreCountPhoneCardError,
    build_score_count_phone_card,
)


def prediction():
    distribution = [
        [20, 24, 20000],
        [24, 20, 30000],
    ]
    td_distribution = [
        [20, 24, 2, 3, 20000],
        [24, 20, 3, 2, 30000],
    ]
    return {
        "schema": PREDICTION_SCHEMA,
        "status": "FROZEN_PREGAME_RESEARCH_PREDICTION",
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "fit_artifact_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "code_identity": "score-count-phone-test",
        "prediction_at": "2026-10-08T20:00:00+00:00",
        "games": [{
            "game_id": "2026_05_KC_BAL",
            "season": 2026,
            "week": 5,
            "kickoff_at": "2026-10-09T00:15:00+00:00",
            "home_team": "BAL",
            "away_team": "KC",
            "prediction_at": "2026-10-08T20:00:00+00:00",
            "paths": 50000,
            "joint_score_distribution": distribution,
            "joint_score_distribution_sha256": "c" * 64,
            "joint_score_td_distribution": td_distribution,
            "joint_score_td_distribution_sha256": "d" * 64,
        }],
        "market_data_present": False,
        "outcome_data_present": False,
        "prediction_sha256": "e" * 64,
    }


def ticket(body: str, observed_at: str = "2026-10-08T21:00:00Z"):
    return tickets_to_dict(parse_nfl_lines(body), observed_at=observed_at)


def board():
    return ticket(
        """
        Chiefs @ Ravens
        ML +120 -140
        Spread +3.5 -110 -110
        Total 44.0 -110 -110
        TeamTotal Ravens 22.5 -110 -110
        """
    )


def test_score_count_phone_prices_game_board_from_frozen_distribution():
    out = build_score_count_phone_card(prediction(), board())
    assert out["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_PHONE_CARD_V1"
    assert out["pricing_policy"]["sportsbook_api_required"] is False
    assert out["pricing_policy"]["straight_price_ceiling"] == -165
    rows = out["rows"]
    assert len(rows) == 8
    assert all(row["status"] == "PRICED" for row in rows)
    home_ml = next(
        row
        for row in rows
        if row["market"] == "moneyline" and row["selection"] == "BAL"
    )
    assert home_ml["estimate_p"] == pytest.approx(0.60)
    assert home_ml["score_label"] == "SPORTSEDGE_QUALIFICATION_ROLE_SCORE_V1"
    assert home_ml["score_0_100"] == 75
    assert home_ml["selected"] is True


def test_quote_change_does_not_change_model_probability_or_score():
    base = board()
    shifted = copy.deepcopy(base)
    shifted["games"][0]["markets"][0]["away_or_over_price"] = +150
    shifted["games"][0]["markets"][0]["home_or_under_price"] = -170

    a = build_score_count_phone_card(prediction(), base)
    b = build_score_count_phone_card(prediction(), shifted)
    a_home = next(
        row for row in a["rows"]
        if row["market"] == "moneyline" and row["selection"] == "BAL"
    )
    b_home = next(
        row for row in b["rows"]
        if row["market"] == "moneyline" and row["selection"] == "BAL"
    )
    assert a_home["estimate_p"] == b_home["estimate_p"] == pytest.approx(0.60)
    assert a_home["score_0_100"] == b_home["score_0_100"] == 75
    assert a_home["ev_per_dollar"] != b_home["ev_per_dollar"]
    assert b_home["card_eligible"] is False
    assert b_home["card_reason"] == "PRICE_ABOVE_STRAIGHT_CEILING"


def test_prediction_must_precede_manual_market_binding():
    with pytest.raises(
        ScoreCountPhoneCardError,
        match="PREDICTION_MUST_PRECEDE_MARKET_BINDING",
    ):
        build_score_count_phone_card(
            prediction(),
            board(),
        ) if False else build_score_count_phone_card(
            prediction(),
            ticket("Chiefs @ Ravens\nML +120 -140", observed_at="2026-10-08T20:00:00Z"),
        )


def test_props_fail_closed_without_live_role_models_while_game_markets_survive():
    mixed = ticket(
        """
        Chiefs @ Ravens
        ML +120 -140
        Prop "Lamar Jackson" PassYards 249.5 -110 -110
        """
    )
    out = build_score_count_phone_card(prediction(), mixed)
    game_rows = [row for row in out["rows"] if row["market"] == "moneyline"]
    prop_rows = [row for row in out["rows"] if row["market"] == "passing_yards"]
    assert all(row["status"] == "PRICED" for row in game_rows)
    assert len(prop_rows) == 2
    assert all(row["status"] == "NO_MODEL" for row in prop_rows)
    assert all(row["reason"] == "LIVE_ROLE_MODEL_REQUIRED" for row in prop_rows)
