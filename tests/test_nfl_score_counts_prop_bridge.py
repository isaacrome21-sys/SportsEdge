import pytest

from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_props_from_paths,
)


def qb(name="QB"):
    return {
        "player": name,
        "position": "QB",
        "role_prior": {
            "pass_attempts": 34.0,
            "completion_rate": 0.66,
            "pass_yards_per_completion": 11.0,
            "pass_td_rate": 0.05,
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


def team(prefix):
    return {
        "qb": qb(f"{prefix}_QB"),
        "pass_td_share": 0.65,
        "skill_players": [
            skill(f"{prefix}_RB", "RB", 5.0, 0.75, 8.0, 15.0, 4.3),
            skill(f"{prefix}_WR", "WR", 9.0, 0.67, 12.0, 0.2, 4.0),
            skill(f"{prefix}_OTHER", "OTHER", 6.0, 0.62, 9.0, 2.5, 4.0),
        ],
    }


def paths(n=300):
    out = []
    for i in range(n):
        out.append({
            "simulation_id": i,
            "home_score": 24 if i % 2 == 0 else 20,
            "away_score": 20 if i % 3 else 27,
        })
    return out


def test_score_count_paths_drive_qb_rb_wr_props_without_second_score_model():
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths(),
        prop_requests=[
            {"team": "home", "player": "H_QB", "market": "passing_yards", "selection": "over", "line": 225.5},
            {"team": "home", "player": "H_RB", "market": "rushing_yards", "selection": "over", "line": 60.5},
            {"team": "home", "player": "H_WR", "market": "receptions", "selection": "over", "line": 5.5},
        ],
        home_model=team("H"),
        away_model=team("A"),
        seed=17,
    )
    assert out["score_path_count"] == 300
    assert len(out["prop_markets"]) == 3
    for row in out["prop_markets"]:
        assert row["status"] == "PRICED_RESEARCH"
        assert row["estimate_p"] + row["loss_p"] + row["push_p"] == pytest.approx(1.0)


def test_td_prop_fails_closed_without_scoring_composition_prior_but_yards_survive():
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths(120),
        prop_requests=[
            {"team": "home", "player": "H_QB", "market": "pass_tds", "selection": "over", "line": 1.5},
            {"team": "home", "player": "H_QB", "market": "passing_yards", "selection": "over", "line": 225.5},
        ],
        home_model=team("H"),
        away_model=team("A"),
        seed=3,
    )
    td, yards = out["prop_markets"]
    assert td["status"] == "NO_MODEL"
    assert td["reason"] == "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
    assert yards["status"] == "PRICED_RESEARCH"


def test_missing_team_model_blocks_only_that_team_requests():
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths(80),
        prop_requests=[
            {"team": "home", "player": "H_QB", "market": "passing_yards", "selection": "over", "line": 225.5},
        ],
        home_model=None,
        away_model=team("A"),
    )
    assert out["prop_markets"][0]["status"] == "NO_MODEL"
    assert "TEAM_MODEL_REQUIRED" in out["prop_markets"][0]["reason"]


def test_direct_team_td_paths_price_td_props_without_second_prior():
    rows = paths(240)
    for idx, row in enumerate(rows):
        row["home_team_tds"] = 3 if idx % 2 == 0 else 2
        row["away_team_tds"] = 2 if idx % 3 else 3
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=rows,
        prop_requests=[
            {"team": "home", "player": "H_QB", "market": "pass_tds", "selection": "over", "line": 1.5},
            {"team": "home", "player": "H_WR", "market": "anytime_tds", "selection": "over", "line": 0.5},
        ],
        home_model=team("H"),
        away_model=team("A"),
        scoring_prior=None,
        seed=13,
    )
    assert [row["status"] for row in out["prop_markets"]] == [
        "PRICED_RESEARCH",
        "PRICED_RESEARCH",
    ]


def test_partial_direct_td_paths_fail_closed_for_td_only():
    rows = paths(40)
    rows[0]["home_team_tds"] = 2
    rows[0]["away_team_tds"] = 2
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=rows,
        prop_requests=[
            {"team": "home", "player": "H_QB", "market": "pass_tds", "selection": "over", "line": 1.5},
            {"team": "home", "player": "H_QB", "market": "passing_yards", "selection": "over", "line": 225.5},
        ],
        home_model=team("H"),
        away_model=team("A"),
        seed=7,
    )
    td, yards = out["prop_markets"]
    assert td["status"] == "NO_MODEL"
    assert td["reason"] == "DIRECT_TD_PATHS_INCOMPLETE"
    assert yards["status"] == "PRICED_RESEARCH"
