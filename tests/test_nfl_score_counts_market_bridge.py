import pytest

from sportsedge.sports.nfl.score_counts_artifact import PREDICTION_SCHEMA
from sportsedge.sports.nfl.score_counts_market_bridge import (
    ScoreCountMarketBridgeError,
    price_score_count_game_markets,
    score_count_grid,
    score_count_paths,
)


def prediction():
    return {
        "schema": PREDICTION_SCHEMA,
        "fit_artifact_sha256": "a" * 64,
        "prediction_sha256": "b" * 64,
        "games": [{
            "game_id": "2026_05_TB_DAL",
            "paths": 50000,
            "joint_score_distribution": [
                [20, 20, 5000],
                [24, 20, 30000],
                [20, 24, 15000],
            ],
            "joint_score_distribution_sha256": "c" * 64,
        }],
    }


def test_bridge_preserves_exact_joint_probability_mass():
    grid = score_count_grid(prediction()["games"][0])
    assert grid[20][20] == pytest.approx(0.10)
    assert grid[24][20] == pytest.approx(0.60)
    assert grid[20][24] == pytest.approx(0.30)
    assert sum(sum(row) for row in grid) == pytest.approx(1.0)


def test_bridge_prices_ml_spread_total_and_team_total_from_same_grid():
    out = price_score_count_game_markets(
        prediction(),
        game_id="2026_05_TB_DAL",
        requests=[
            {"market": "moneyline", "selection": "home"},
            {"market": "spread", "selection": "home", "line": -4},
            {"market": "total", "selection": "over", "line": 44},
            {"market": "team_total", "team": "home", "selection": "over", "line": 22},
            {"market": "team_total", "team": "away", "selection": "over", "line": 22},
        ],
    )
    rows = out["game_markets"]
    assert rows[0]["estimate_p"] == pytest.approx(0.60)
    assert rows[0]["push_p"] == pytest.approx(0.10)
    assert rows[1]["push_p"] == pytest.approx(0.60)
    assert rows[2]["push_p"] == pytest.approx(0.90)
    assert rows[3]["estimate_p"] == pytest.approx(0.60)
    assert rows[4]["estimate_p"] == pytest.approx(0.30)
    assert out["market_data_used_to_create_distribution"] is False


def test_exact_paths_expand_without_second_score_model():
    rows = score_count_paths(prediction()["games"][0])
    assert len(rows) == 50000
    assert sum(row["home_score"] == 24 and row["away_score"] == 20 for row in rows) == 30000
    assert rows[0]["simulation_id"] == 0
    assert rows[-1]["simulation_id"] == 49999


def test_invalid_mass_or_wrong_path_count_fails_closed():
    bad = prediction()["games"][0]
    bad["paths"] = 49999
    with pytest.raises(ScoreCountMarketBridgeError, match="PATHS_MUST_EQUAL_50000"):
        score_count_grid(bad)

    bad = prediction()["games"][0]
    bad["joint_score_distribution"][0][2] = 4999
    with pytest.raises(ScoreCountMarketBridgeError, match="PATH_MASS_MISMATCH"):
        score_count_grid(bad)
