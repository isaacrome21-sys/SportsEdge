import copy

import pytest

from sportsedge.sports.nfl.unified_market_engine import (
    price_game_market,
    run_unified_nfl_model,
    sample_score_paths,
)


def tiny_grid():
    # [home][away]
    # 0-0 tie 10%, 1-0 home 60%, 0-1 away 30%
    return [
        [0.10, 0.30],
        [0.60, 0.00],
    ]


def qb(name="QB"):
    return {
        "player": name,
        "position": "QB",
        "role_prior": {
            "pass_attempts": 34.0,
            "completion_rate": 0.66,
            "pass_yards_per_completion": 11.0,
            "pass_td_rate": 0.050,
            "interception_rate": 0.025,
            "rush_attempts": 4.0,
            "rush_yards_per_attempt": 4.5,
            "targets": 0.0,
            "catch_rate": 0.0,
            "receiving_yards_per_reception": 0.0,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.06},
    }


def skill(name, position, targets, catch_rate, ypr, carries, ypc):
    return {
        "player": name,
        "position": position,
        "role_prior": {
            "pass_attempts": 0.0,
            "completion_rate": 0.0,
            "pass_yards_per_completion": 0.0,
            "pass_td_rate": 0.0,
            "interception_rate": 0.0,
            "rush_attempts": carries,
            "rush_yards_per_attempt": ypc,
            "targets": targets,
            "catch_rate": catch_rate,
            "receiving_yards_per_reception": ypr,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.06},
    }


def team_model(prefix):
    return {
        "qb": qb(f"{prefix}_QB"),
        "skill_players": [
            skill(f"{prefix}_RB1", "RB", 5.5, 0.76, 8.2, 15.0, 4.3),
            skill(f"{prefix}_WR1", "WR", 9.0, 0.67, 12.1, 0.4, 5.0),
            skill(f"{prefix}_WR2", "WR", 6.5, 0.64, 10.8, 0.2, 4.5),
            skill(f"{prefix}_OTHER", "OTHER", 5.0, 0.62, 8.8, 3.0, 4.0),
        ],
    }


def assert_probability_row(row):
    assert row["status"] == "PRICED_RESEARCH"
    assert 0.0 <= row["estimate_p"] <= 1.0
    assert 0.0 <= row["loss_p"] <= 1.0
    assert 0.0 <= row["push_p"] <= 1.0
    assert row["estimate_p"] + row["loss_p"] + row["push_p"] == pytest.approx(1.0)


def test_moneyline_treats_final_tie_as_push():
    home = price_game_market(tiny_grid(), {"market": "moneyline", "selection": "home"})
    away = price_game_market(tiny_grid(), {"market": "moneyline", "selection": "away"})
    assert home["estimate_p"] == pytest.approx(0.60)
    assert away["estimate_p"] == pytest.approx(0.30)
    assert home["push_p"] == pytest.approx(0.10)
    assert away["push_p"] == pytest.approx(0.10)
    assert home["conditional_win_probability"] == pytest.approx(2.0 / 3.0)


def test_integer_spread_and_total_keep_real_push_mass():
    spread = price_game_market(
        tiny_grid(), {"market": "spread", "selection": "home", "line": 0.0}
    )
    total = price_game_market(
        tiny_grid(), {"market": "total", "selection": "over", "line": 1.0}
    )
    assert spread["estimate_p"] == pytest.approx(0.60)
    assert spread["push_p"] == pytest.approx(0.10)
    assert total["estimate_p"] == pytest.approx(0.0)
    assert total["push_p"] == pytest.approx(0.90)
    assert total["loss_p"] == pytest.approx(0.10)


def test_away_spread_line_is_applied_to_away_team_not_home_team():
    grid = [
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],  # home wins 3-0
    ]
    away_plus_three = price_game_market(
        grid, {"market": "spread", "selection": "away", "line": 3.0}
    )
    away_plus_three_half = price_game_market(
        grid, {"market": "spread", "selection": "away", "line": 3.5}
    )
    assert away_plus_three["push_p"] == pytest.approx(1.0)
    assert away_plus_three["estimate_p"] == pytest.approx(0.0)
    assert away_plus_three_half["estimate_p"] == pytest.approx(1.0)
    assert away_plus_three_half["push_p"] == pytest.approx(0.0)


def test_team_total_comes_from_same_score_grid():
    home_over = price_game_market(
        tiny_grid(),
        {"market": "team_total", "team": "home", "selection": "over", "line": 0.5},
    )
    away_over = price_game_market(
        tiny_grid(),
        {"market": "team_total", "team": "away", "selection": "over", "line": 0.5},
    )
    assert home_over["estimate_p"] == pytest.approx(0.60)
    assert away_over["estimate_p"] == pytest.approx(0.30)


def test_score_path_sampling_is_seeded_and_deterministic():
    a = sample_score_paths(tiny_grid(), n_sims=100, seed=7)
    b = sample_score_paths(tiny_grid(), n_sims=100, seed=7)
    c = sample_score_paths(tiny_grid(), n_sims=100, seed=8)
    assert a == b
    assert a != c
    assert all(set(row) == {"simulation_id", "home_score", "away_score"} for row in a)


def test_one_unified_run_prices_game_and_qb_rb_wr_markets():
    out = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=3.0,
        attempt9_total=45.0,
        game_markets=[
            {"market": "moneyline", "selection": "home"},
            {"market": "spread", "selection": "home", "line": -3.0},
            {"market": "total", "selection": "under", "line": 45.5},
            {"market": "team_total", "team": "home", "selection": "over", "line": 23.5},
        ],
        prop_markets=[
            {
                "team": "home",
                "player": "H_QB",
                "market": "passing_yards",
                "selection": "over",
                "line": 239.5,
            },
            {
                "team": "home",
                "player": "H_RB1",
                "market": "rushing_yards",
                "selection": "over",
                "line": 64.5,
            },
            {
                "team": "home",
                "player": "H_WR1",
                "market": "receiving_yards",
                "selection": "over",
                "line": 69.5,
            },
            {
                "team": "home",
                "player": "H_WR1",
                "market": "receptions",
                "selection": "over",
                "line": 5.5,
            },
        ],
        home_model=team_model("H"),
        away_model=team_model("A"),
        n_sims=1200,
        seed=91,
    )

    assert out["schema"] == "SPORTSEDGE_NFL_UNIFIED_RESEARCH_MARKET_ENGINE_V1"
    assert out["score_distribution"]["sampled_paths"] == 1200
    assert out["score_distribution"]["family"].startswith("B_INDEPENDENT_NB")
    assert out["workload_coupling"]["lead_trail_pass_rush_adjustment"] is False
    assert out["authority"]["research_only"] is True
    assert out["authority"]["creates_model_p"] is False

    assert len(out["game_markets"]) == 4
    assert len(out["prop_markets"]) == 4
    for row in out["game_markets"] + out["prop_markets"]:
        assert_probability_row(row)

    # Exact 3-point outcomes exist in the discrete grid, so an integer -3 can push.
    spread = next(row for row in out["game_markets"] if row["market"] == "spread")
    assert spread["push_p"] > 0.0


def test_run_is_deterministic_for_props_and_game_probabilities():
    kwargs = dict(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=-1.5,
        attempt9_total=41.5,
        game_markets=[
            {"market": "moneyline", "selection": "away"},
            {"market": "spread", "selection": "away", "line": -1.5},
        ],
        prop_markets=[
            {
                "team": "away",
                "player": "A_QB",
                "market": "pass_attempts",
                "selection": "over",
                "line": 33.5,
            },
            {
                "team": "away",
                "player": "A_RB1",
                "market": "rush_receiving_yards",
                "selection": "over",
                "line": 79.5,
            },
        ],
        home_model=team_model("H"),
        away_model=team_model("A"),
        n_sims=700,
        seed=17,
    )
    a = run_unified_nfl_model(**kwargs)
    b = run_unified_nfl_model(**kwargs)
    assert a == b


def test_td_prop_fails_closed_without_scoring_prior_but_other_prop_survives():
    out = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=2.0,
        attempt9_total=44.0,
        prop_markets=[
            {
                "team": "home",
                "player": "H_QB",
                "market": "pass_tds",
                "selection": "over",
                "line": 1.5,
            },
            {
                "team": "home",
                "player": "H_QB",
                "market": "passing_yards",
                "selection": "over",
                "line": 229.5,
            },
        ],
        home_model=team_model("H"),
        away_model=team_model("A"),
        n_sims=400,
        seed=3,
    )
    td, yards = out["prop_markets"]
    assert td["status"] == "NO_MODEL"
    assert td["reason"] == "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
    assert_probability_row(yards)


def test_missing_or_market_contaminated_player_inputs_fail_only_prop_rows():
    missing = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=0.0,
        attempt9_total=42.0,
        game_markets=[{"market": "moneyline", "selection": "home"}],
        prop_markets=[
            {
                "team": "home",
                "player": "H_QB",
                "market": "passing_yards",
                "selection": "over",
                "line": 220.5,
            }
        ],
        home_model=None,
        n_sims=200,
        seed=5,
    )
    assert_probability_row(missing["game_markets"][0])
    assert missing["prop_markets"][0]["status"] == "NO_MODEL"
    assert "TEAM_MODEL_REQUIRED" in missing["prop_markets"][0]["reason"]

    contaminated_model = team_model("H")
    contaminated_model["qb"] = copy.deepcopy(contaminated_model["qb"])
    contaminated_model["qb"]["sportsbook_probability"] = 0.55
    contaminated = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=0.0,
        attempt9_total=42.0,
        prop_markets=[
            {
                "team": "home",
                "player": "H_QB",
                "market": "passing_yards",
                "selection": "over",
                "line": 220.5,
            }
        ],
        home_model=contaminated_model,
        n_sims=200,
        seed=5,
    )
    assert contaminated["prop_markets"][0]["status"] == "NO_MODEL"
    assert "MARKET_INPUT_FORBIDDEN" in contaminated["prop_markets"][0]["reason"]

def test_signed_low_volume_receiving_efficiency_does_not_poison_team_simulation():
    home = team_model("H")
    # A one-catch negative-yard sample is legitimate football data.  It should
    # contribute zero positive yard-allocation weight rather than crashing the
    # entire team simulation while the pooled receiving efficiency stays valid.
    home["skill_players"][3]["role_prior"]["receiving_yards_per_reception"] = -2.0
    out = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=1.0,
        attempt9_total=43.0,
        prop_markets=[
            {
                "team": "home",
                "player": "H_WR1",
                "market": "receiving_yards",
                "selection": "over",
                "line": 65.5,
            },
            {
                "team": "away",
                "player": "A_WR1",
                "market": "receiving_yards",
                "selection": "over",
                "line": 65.5,
            },
        ],
        home_model=home,
        away_model=team_model("A"),
        n_sims=400,
        seed=119,
    )
    assert out["prop_board_status"] == "AVAILABLE"
    assert out["prop_board_error"] is None
    assert out["team_simulation_errors"] == {}
    assert all(row["status"] == "PRICED_RESEARCH" for row in out["prop_markets"])


def test_any_requested_team_simulation_error_fails_entire_prop_board_closed():
    broken_home = team_model("H")
    for player in broken_home["skill_players"]:
        player["role_prior"]["receiving_yards_per_reception"] = 0.0

    out = run_unified_nfl_model(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=1.0,
        attempt9_total=43.0,
        prop_markets=[
            {
                "team": "home",
                "player": "H_WR1",
                "market": "receiving_yards",
                "selection": "over",
                "line": 65.5,
            },
            {
                "team": "away",
                "player": "A_WR1",
                "market": "receiving_yards",
                "selection": "over",
                "line": 65.5,
            },
        ],
        home_model=broken_home,
        away_model=team_model("A"),
        n_sims=300,
        seed=120,
    )
    assert out["prop_board_status"] == "NO_MODEL"
    assert out["prop_board_error"].startswith("GAME_PROP_SIMULATION_INCOMPLETE:home=")
    assert "home" in out["team_simulation_errors"]
    assert len(out["prop_markets"]) == 2
    assert all(row["status"] == "NO_MODEL" for row in out["prop_markets"])
    assert all(
        row["reason"] == out["prop_board_error"]
        for row in out["prop_markets"]
    )

