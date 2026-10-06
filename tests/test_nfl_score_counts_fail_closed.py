"""Score-count prop board must not survive a one-team simulation failure."""

from sportsedge.nfl_prop_shared_sim import stabilized_role
from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_props_from_paths,
)


def _role(ypr: float = 8.0) -> dict:
    return {
        "player": "WR",
        "sample_size": 1,
        "role_prior": {
            "pass_attempts": 30,
            "completion_rate": 0.65,
            "pass_yards_per_completion": 7.5,
            "pass_td_rate": 0.04,
            "interception_rate": 0.02,
            "rush_attempts": 3,
            "rush_yards_per_attempt": 4.2,
            "targets": 6,
            "catch_rate": 0.65,
            "receiving_yards_per_reception": 8.0,
        },
        "trailing": {"receiving_yards_per_reception": ypr},
        "context": {"source": "role"},
    }


def test_signed_receiving_efficiency_does_not_invalidate_role():
    role = stabilized_role(_role(-2.0))
    assert role["receiving_yards_per_reception"] < 8.0
    assert role["receiving_yards_per_reception"] != 0.0


def test_either_team_simulation_failure_fails_score_count_prop_board():
    paths = [{"home_score": 20, "away_score": 17}]
    out = price_score_count_props_from_paths(
        game_id="2026_05_ATL_NO",
        score_paths=paths,
        prop_requests=[
            {"team": "home", "player": "NO_WR", "market": "receiving_yards", "selection": "under", "line": 40.5},
            {"team": "away", "player": "ATL_WR", "market": "receiving_yards", "selection": "under", "line": 40.5},
        ],
        home_model={"qb": {}, "skill_players": [{"player": "NO_WR"}]},
        away_model={"qb": {"player": "ATL_QB"}, "skill_players": [{"player": "ATL_WR"}]},
        seed=7,
    )
    assert out["prop_board_status"] == "NO_MODEL"
    assert out["prop_board_error"].startswith("GAME_PROP_SIMULATION_INCOMPLETE:")
    assert len(out["prop_markets"]) == 2
    assert all(row["status"] == "NO_MODEL" for row in out["prop_markets"])
    assert all(row["reason"] == out["prop_board_error"] for row in out["prop_markets"])
