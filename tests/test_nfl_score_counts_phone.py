from pathlib import Path
import pytest

from sportsedge.nfl_score_counts_phone import (
    _apply_prop_selection_policy,
    _prop_selection_diagnostics,
    build_score_count_phone_card,
)
from scripts.run_nfl_score_counts_lines_card import _game_only_ticket
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


def test_fast_game_ticket_preserves_all_game_markets_and_strips_props():
    full = ticket()
    full["games"][0]["markets"].append({
        "market": "receiving_yards",
        "player": "A_WR",
        "line": 55.5,
        "away_or_over_price": -110,
        "home_or_under_price": -110,
    })
    fast = _game_only_ticket(full)
    markets = fast["games"][0]["markets"]
    assert [row["market"] for row in markets] == [
        "moneyline", "spread", "total", "team_total"
    ]
    assert fast["observed_at"] == full["observed_at"]
    assert all(not str(row.get("player") or "").strip() for row in markets)


def test_fast_game_output_precedes_prop_context_fetch():
    text = Path("scripts/run_nfl_score_counts_lines_card.py").read_text(encoding="utf-8")
    fast = text.index("if args.fast_game_output:")
    props = text.index("if _has_props(ticket):", fast)
    assert fast < props
    assert "fast_game_markets_only" in text
    assert "NOT_REQUIRED_FOR_GAME_MARKETS" in text

def test_prop_team_failure_does_not_invalidate_score_count_game_markets(monkeypatch):
    def fake_live_team_model(**kwargs):
        return team(str(kwargs["team"]))

    def fake_prop_bridge(prediction, **kwargs):
        reqs = kwargs["prop_requests"]
        reason = "GAME_PROP_SIMULATION_INCOMPLETE:home=TEAM_MODEL_REQUIRED"
        return {
            "prop_markets": [
                {
                    **req,
                    "status": "NO_MODEL",
                    "reason": reason,
                }
                for req in reqs
            ],
            "prop_board_status": "NO_MODEL",
            "prop_board_error": reason,
            "team_simulation_errors": {"home": "TEAM_MODEL_REQUIRED"},
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
        "games": [{
            "away": "A",
            "home": "B",
            "markets": [
                {
                    "market": "moneyline",
                    "away_or_over_price": 110,
                    "home_or_under_price": -130,
                },
                {
                    "market": "receiving_yards",
                    "player": "B_WR",
                    "line": 64.5,
                    "away_or_over_price": -105,
                    "home_or_under_price": -115,
                },
            ],
        }],
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
    game = out["games"][0]
    moneyline = [row for row in game["rows"] if row["market"] == "moneyline"]
    props = [row for row in game["rows"] if row["market"] == "receiving_yards"]
    assert len(moneyline) == 2
    assert all(row["status"] == "PRICED" for row in moneyline)
    assert len(props) == 2
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert game["status"] == "PRICED_SCORE_COUNTS_RESEARCH"
    assert game["role_status"] == "NO_MODEL"
    assert game["engine"]["prop_board_status"] == "NO_MODEL"

def test_single_team_quoted_props_do_not_require_unquoted_team_role_model(monkeypatch):
    calls = []

    def fake_live_team_model(**kwargs):
        team_name = str(kwargs["team"])
        calls.append(team_name)
        if team_name == "B":
            raise ValueError("B_ROLE_BROKEN")
        return team(team_name)

    def fake_prop_bridge(prediction, **kwargs):
        assert kwargs["home_model"] is None
        assert kwargs["away_model"] is not None
        assert {row["team"] for row in kwargs["prop_requests"]} == {"away"}
        return {
            "prop_markets": [
                {
                    **req,
                    "estimate_p": 0.60 if req["selection"] == "over" else 0.40,
                    "loss_p": 0.40 if req["selection"] == "over" else 0.60,
                    "push_p": 0.0,
                    "conditional_win_probability": 0.60 if req["selection"] == "over" else 0.40,
                    "fair_american": -150.0 if req["selection"] == "over" else 150.0,
                    "status": "PRICED_RESEARCH",
                }
                for req in kwargs["prop_requests"]
            ],
            "prop_board_status": "AVAILABLE",
            "prop_board_error": None,
            "team_simulation_errors": {},
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
        "games": [{
            "away": "A",
            "home": "B",
            "markets": [{
                "market": "receiving_yards",
                "team": "A",
                "player": "A_WR",
                "line": 45.5,
                "away_or_over_price": -110,
                "home_or_under_price": -110,
            }],
        }],
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
    assert calls == ["A"]
    game = out["games"][0]
    assert game["role_status"] == "AVAILABLE"
    assert game["engine"]["role_model_errors_by_side"] == {}
    props = [row for row in game["rows"] if row["market"] == "receiving_yards"]
    assert len(props) == 2
    assert all(row["status"] == "PRICED" for row in props)


def test_two_team_quoted_props_fail_closed_when_one_requested_role_model_build_fails(monkeypatch):
    def fake_live_team_model(**kwargs):
        team_name = str(kwargs["team"])
        if team_name == "B":
            raise ValueError("B_ROLE_BROKEN")
        return team(team_name)

    monkeypatch.setattr(
        "sportsedge.nfl_score_counts_phone.build_live_team_model",
        fake_live_team_model,
    )

    board = {
        "observed_at": "2026-10-05T16:00:00+00:00",
        "games": [{
            "away": "A",
            "home": "B",
            "markets": [
                {
                    "market": "receiving_yards",
                    "team": "A",
                    "player": "A_WR",
                    "line": 45.5,
                    "away_or_over_price": -110,
                    "home_or_under_price": -110,
                },
                {
                    "market": "receiving_yards",
                    "team": "B",
                    "player": "B_WR",
                    "line": 45.5,
                    "away_or_over_price": -110,
                    "home_or_under_price": -110,
                },
            ],
        }],
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
    game = out["games"][0]
    assert game["role_status"] == "NO_MODEL"
    assert game["role_error"].startswith("GAME_PROP_ROLE_MODEL_INCOMPLETE:")
    assert game["engine"]["role_model_errors_by_side"] == {"home": "B_ROLE_BROKEN"}
    props = [row for row in game["rows"] if row["market"] == "receiving_yards"]
    assert len(props) == 4
    assert all(row["status"] == "NO_MODEL" for row in props)
    assert all(row["reason"] == game["role_error"] for row in props)

def test_score_count_prop_selection_trims_same_player_pass_volume_duplicates():
    raw_game = {
        "markets": [
            {"player": "QB", "market": "pass_attempts"},
            {"player": "QB", "market": "completions"},
            {"player": "QB", "market": "passing_yards"},
        ]
    }
    rows = [
        {
            "input_index": 0, "player": "QB", "market": "pass_attempts",
            "status": "PRICED", "selected": True, "selection": "QB Under",
            "ev_per_dollar": 0.08, "edge_probability_points": 0.08, "score_0_100": 88,
        },
        {
            "input_index": 1, "player": "QB", "market": "completions",
            "status": "PRICED", "selected": True, "selection": "QB Under",
            "ev_per_dollar": 0.11, "edge_probability_points": 0.10, "score_0_100": 88,
        },
        {
            "input_index": 2, "player": "QB", "market": "passing_yards",
            "status": "PRICED", "selected": True, "selection": "QB Under",
            "ev_per_dollar": 0.17, "edge_probability_points": 0.14, "score_0_100": 88,
        },
    ]
    policy = _apply_prop_selection_policy(rows, raw_game)
    kept = [row for row in rows if row.get("selected")]
    assert len(kept) == 1
    assert kept[0]["market"] == "passing_yards"
    assert policy["candidate_pair_selections"] == 3
    assert policy["served_prop_selections"] == 1
    assert policy["forces_team_balance"] is False
    assert policy["forces_over_under_balance"] is False


def test_score_count_prop_selection_caps_six_independent_props_without_rebalancing():
    raw_game = {
        "markets": [
            {"player": f"P{i}", "market": "receiving_yards"}
            for i in range(7)
        ]
    }
    rows = [
        {
            "input_index": i, "player": f"P{i}", "team": "away",
            "market": "receiving_yards", "status": "PRICED", "selected": True,
            "selection": f"P{i} Under", "ev_per_dollar": 0.20 - i * 0.01,
            "edge_probability_points": 0.20 - i * 0.01, "score_0_100": 88,
        }
        for i in range(7)
    ]
    policy = _apply_prop_selection_policy(rows, raw_game)
    kept = [row for row in rows if row.get("selected")]
    assert len(kept) == 6
    assert all(row["team"] == "away" for row in kept)
    assert all(str(row["selection"]).endswith("Under") for row in kept)
    suppressed = [row for row in rows if not row.get("selected")]
    assert len(suppressed) == 1
    assert suppressed[0]["selection_suppressed_reason"] == "PROP_CARD_DISPLAY_CAP"
    assert policy["forces_team_balance"] is False
    assert policy["forces_over_under_balance"] is False


def test_score_count_concentration_diagnostic_flags_review_but_does_not_change_selection():
    raw_game = {
        "markets": [
            {"player": f"ATL{i}", "market": "receiving_yards"}
            for i in range(6)
        ] + [
            {"player": "NO1", "market": "receiving_yards"},
        ]
    }
    rows = [
        {
            "input_index": i, "player": f"ATL{i}", "team": "away",
            "market": "receiving_yards", "status": "PRICED", "selected": True,
            "selection": f"ATL{i} Under",
        }
        for i in range(6)
    ] + [{
        "input_index": 6, "player": "NO1", "team": "home",
        "market": "receiving_yards", "status": "PRICED", "selected": False,
        "selection": "NO1 Over",
    }]
    before = [row.get("selected") for row in rows]
    diag = _prop_selection_diagnostics(rows, raw_game)
    after = [row.get("selected") for row in rows]
    assert before == after
    assert diag["review_required"] is True
    assert "ALL_SELECTED_PROPS_ONE_TEAM_WITH_TWO_TEAM_PRICING" in diag["alerts"]
    assert "SELECTED_PROP_DIRECTION_CONCENTRATED_UNDER" in diag["alerts"]
    assert diag["selection_changed_by_diagnostic"] is False

