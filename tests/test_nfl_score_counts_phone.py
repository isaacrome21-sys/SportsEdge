import pytest

from sportsedge.nfl_score_counts_phone import build_score_count_phone_card
from sportsedge.nfl_unified_phone import UnifiedNflPhoneError


def prediction(prediction_at="2026-10-05T15:00:00+00:00"):
    return {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_PREDICTION_V1",
        "prediction_at": prediction_at,
        "fit_artifact_sha256": "a" * 64,
        "prediction_sha256": "b" * 64,
        "games": [
            {
                "game_id": "2026_05_A_B",
                "season": 2026,
                "week": 5,
                "kickoff_at": "2026-10-09T00:15:00+00:00",
                "home_team": "B",
                "away_team": "A",
                "prediction_at": prediction_at,
                "paths": 50000,
                "joint_score_distribution": [
                    [24, 20, 20000],
                    [20, 24, 15000],
                    [27, 20, 10000],
                    [17, 20, 5000],
                ],
                "joint_score_distribution_sha256": "c" * 64,
                "means": {
                    "home_score": 22.4,
                    "away_score": 21.2,
                    "margin": 1.2,
                    "total": 43.6,
                },
            }
        ],
    }


def schedule():
    return [
        {
            "game_id": "2026_05_A_B",
            "away_team_id": "A",
            "home_team_id": "B",
            "season": 2026,
            "week": 5,
            "kickoff_ts": "2026-10-09T00:15:00+00:00",
        }
    ]


def ticket(observed_at="2026-10-05T16:00:00+00:00"):
    return {
        "observed_at": observed_at,
        "games": [
            {
                "away": "A",
                "home": "B",
                "markets": [
                    {
                        "market": "moneyline",
                        "away_or_over_price": 110,
                        "home_or_under_price": -130,
                    },
                    {
                        "market": "spread",
                        "line": 3.5,
                        "away_or_over_price": -110,
                        "home_or_under_price": -110,
                    },
                    {
                        "market": "total",
                        "line": 42.5,
                        "away_or_over_price": -110,
                        "home_or_under_price": -110,
                    },
                    {
                        "market": "team_total",
                        "team": "B",
                        "line": 21.5,
                        "away_or_over_price": -110,
                        "home_or_under_price": -110,
                    },
                ],
            }
        ],
    }


def team(prefix):
    return {
        "qb": {
            "player": f"{prefix}_QB",
            "position": "QB",
            "rushing_td_share": 0.08,
        },
        "skill_players": [
            {
                "player": f"{prefix}_WR",
                "position": "WR",
                "receiving_td_share": 0.40,
                "rushing_td_share": 0.01,
            }
        ],
        "pass_td_share": 0.65,
    }


def test_game_markets_are_priced_from_frozen_score_count_distribution():
    out = build_score_count_phone_card(
        ticket(),
        prediction=prediction(),
        schedule_games=schedule(),
    )
    assert out["candidate_family"] == "NFL_SCORE_COUNTS_G1"
    assert out["pricing_policy"]["game_markets_disabled"] is False
    assert len(out["rows"]) == 8
    assert all(row["status"] == "PRICED" for row in out["rows"])
    assert {row["market"] for row in out["rows"]} == {
        "moneyline",
        "spread",
        "total",
        "team_total",
    }
    assert out["games"][0]["engine"]["paths"] == 50000
    assert out["games"][0]["engine"]["market_data_used_to_create_distribution"] is False


def test_prediction_must_exist_before_quote_binding():
    with pytest.raises(
        UnifiedNflPhoneError,
        match="SCORE_COUNT_PREDICTION_NOT_BEFORE_QUOTE_BINDING",
    ):
        build_score_count_phone_card(
            ticket(observed_at="2026-10-05T14:59:59+00:00"),
            prediction=prediction(),
            schedule_games=schedule(),
        )


def test_prop_rows_delegate_to_score_count_prop_bridge(monkeypatch):
    def fake_live_team_model(**kwargs):
        return team(str(kwargs["team"]))

    def fake_prop_bridge(prediction, **kwargs):
        reqs = kwargs["prop_requests"]
        return {
            "prop_markets": [
                {
                    **req,
                    "estimate_p": 0.58 if req["selection"] == "over" else 0.42,
                    "loss_p": 0.42 if req["selection"] == "over" else 0.58,
                    "push_p": 0.0,
                    "conditional_win_probability": 0.58 if req["selection"] == "over" else 0.42,
                    "fair_american": -138.095 if req["selection"] == "over" else 138.095,
                    "status": "PRICED_RESEARCH",
                }
                for req in reqs
            ]
        }

    monkeypatch.setattr(
        "sportsedge.nfl_score_counts_phone.build_live_team_model",
        fake_live_team_model,
    )
    monkeypatch.setattr(
        "sportsedge.nfl_score_counts_phone.price_score_count_prop_markets",
        fake_prop_bridge,
    )

    board = {
        "observed_at": "2026-10-05T16:00:00+00:00",
        "games": [
            {
                "away": "A",
                "home": "B",
                "markets": [
                    {
                        "market": "receiving_yards",
                        "player": "B_WR",
                        "line": 64.5,
                        "away_or_over_price": -105,
                        "home_or_under_price": -115,
                    }
                ],
            }
        ],
    }
    out = build_score_count_phone_card(
        board,
        prediction=prediction(),
        schedule_games=schedule(),
        depth_rows=[{}],
        player_rows=[{}],
        injury_rows=[{}],
        injury_source_ready=True,
    )
    assert len(out["rows"]) == 2
    assert all(row["status"] == "PRICED" for row in out["rows"])
    assert {row["player"] for row in out["rows"]} == {"B_WR"}
    assert out["pricing_policy"]["prop_game_context_source"] == "NFL_SCORE_COUNTS_G1_SCORE_PATHS"


def test_prediction_at_same_instant_as_quote_is_rejected():
    with pytest.raises(
        UnifiedNflPhoneError,
        match="SCORE_COUNT_PREDICTION_NOT_BEFORE_QUOTE_BINDING",
    ):
        build_score_count_phone_card(
            ticket(observed_at="2026-10-05T15:00:00+00:00"),
            prediction=prediction(prediction_at="2026-10-05T15:00:00+00:00"),
            schedule_games=schedule(),
        )
