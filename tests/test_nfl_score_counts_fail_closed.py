"""Score-count prop board must not survive a one-team simulation failure."""

from sportsedge.sports.nfl.score_counts_prop_bridge import (
    price_score_count_props_from_paths,
)
from scripts.run_nfl_score_counts_lines_card import (
    _name_alias_match,
    _normalize_ticket_prop_players,
)


def _role(ypr: float = 8.0) -> dict:
    return {
        "player": "WR",
        "sample_size": 0,
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
            "receiving_yards_per_reception": ypr,
        },
        "trailing": {},
        "context": {"source": "role"},
    }


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

def _team(prefix: str) -> dict:
    return {
        "qb": {
            "player": f"{prefix}_QB",
            "position": "QB",
            "role_prior": {
                "pass_attempts": 30,
                "completion_rate": 0.65,
                "pass_yards_per_completion": 10.0,
                "pass_td_rate": 0.04,
                "interception_rate": 0.02,
                "rush_attempts": 3,
                "rush_yards_per_attempt": 4.0,
                "targets": 0,
                "catch_rate": 0,
                "receiving_yards_per_reception": 0,
            },
            "trailing": {},
            "sample_size": 0,
            "context": {"source": "role"},
        },
        "skill_players": [
            {
                "player": f"{prefix}_WR",
                "position": "WR",
                "role_prior": {
                    "pass_attempts": 0,
                    "completion_rate": 0,
                    "pass_yards_per_completion": 0,
                    "pass_td_rate": 0,
                    "interception_rate": 0,
                    "rush_attempts": 0,
                    "rush_yards_per_attempt": 0,
                    "targets": 7,
                    "catch_rate": 0.65,
                    "receiving_yards_per_reception": 11.0,
                },
                "trailing": {},
                "sample_size": 0,
                "context": {"source": "role"},
            }
        ],
    }


def test_individual_bad_player_row_does_not_void_healthy_opposite_team():
    paths = [{"home_score": 20, "away_score": 17} for _ in range(40)]
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths,
        prop_requests=[
            {
                "team": "away",
                "player": "ATL_WR",
                "market": "receiving_yards",
                "selection": "over",
                "line": 40.5,
            },
            {
                "team": "home",
                "player": "NOT_IN_MODEL",
                "market": "receiving_yards",
                "selection": "over",
                "line": 40.5,
            },
        ],
        home_model=_team("NO"),
        away_model=_team("ATL"),
        seed=9,
    )
    away, home = out["prop_markets"]
    assert away["status"] == "PRICED_RESEARCH"
    assert home["status"] == "NO_MODEL"
    assert "PROP_PLAYER_NOT_IN_TEAM_MODEL" in home["reason"]
    assert out["prop_board_status"] == "AVAILABLE"
    assert out["prop_board_error"] is None
    assert out["team_simulation_errors"] == {}

def test_score_count_runner_normalizes_pitts_and_branch_aliases_without_affecting_other_rows():
    assert _name_alias_match("Kyle Pitts Sr.", "Kyle Pitts")
    assert _name_alias_match("Zachariah Branch", "Zach Branch")
    ticket = {
        "games": [{
            "away": "ATL",
            "home": "NO",
            "markets": [
                {"player": "Kyle Pitts", "market": "receptions"},
                {"player": "Zach Branch", "market": "receiving_yards"},
                {"market": "total", "line": 44.5},
            ],
        }]
    }
    depth = [
        {"team": "ATL", "player_name": "Kyle Pitts Sr."},
        {"team": "ATL", "player_name": "Zachariah Branch"},
        {"team": "NO", "player_name": "Chris Olave"},
    ]
    normalized, bindings = _normalize_ticket_prop_players(ticket, depth)
    props = normalized["games"][0]["markets"]
    assert props[0]["player"] == "Kyle Pitts Sr."
    assert props[0]["team"] == "ATL"
    assert props[1]["player"] == "Zachariah Branch"
    assert props[1]["team"] == "ATL"
    assert props[2] == {"market": "total", "line": 44.5}
    assert len(bindings) == 2

def test_score_count_bridge_regularizes_single_negative_receiver_without_killing_team():
    home = _team("NO")
    home["skill_players"].append({
        "player": "NO_NEG",
        "position": "RB",
        "role_prior": {
            "pass_attempts": 0,
            "completion_rate": 0,
            "pass_yards_per_completion": 0,
            "pass_td_rate": 0,
            "interception_rate": 0,
            "rush_attempts": 1,
            "rush_yards_per_attempt": 3.0,
            "targets": 1,
            "catch_rate": 1.0,
            "receiving_yards_per_reception": -2.0,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"source": "role"},
    })
    paths = [{"home_score": 23, "away_score": 20} for _ in range(300)]
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths,
        prop_requests=[
            {
                "team": "home",
                "player": "NO_NEG",
                "market": "receiving_yards",
                "selection": "over",
                "line": 0.5,
            },
            {
                "team": "away",
                "player": "ATL_WR",
                "market": "receiving_yards",
                "selection": "over",
                "line": 40.5,
            },
        ],
        home_model=home,
        away_model=_team("ATL"),
        seed=11,
    )
    assert out["prop_board_status"] == "AVAILABLE"
    assert out["team_simulation_errors"] == {}
    assert all(row["status"] == "PRICED_RESEARCH" for row in out["prop_markets"])
    audit = out["receiving_efficiency_regularization"]["home"]
    assert len(audit) == 1
    assert audit[0]["player"] == "NO_NEG"
    assert audit[0]["observed_stabilized_ypr"] == -2.0
    assert audit[0]["replacement_ypr"] > 0


def test_score_count_bridge_does_not_invent_receiver_efficiency_when_whole_pool_is_nonpositive():
    home = _team("NO")
    for row in home["skill_players"]:
        row["role_prior"]["receiving_yards_per_reception"] = -2.0
    paths = [{"home_score": 20, "away_score": 17} for _ in range(20)]
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths,
        prop_requests=[
            {
                "team": "home",
                "player": "NO_WR",
                "market": "receiving_yards",
                "selection": "under",
                "line": 40.5,
            },
            {
                "team": "away",
                "player": "ATL_WR",
                "market": "receiving_yards",
                "selection": "over",
                "line": 40.5,
            },
        ],
        home_model=home,
        away_model=_team("ATL"),
        seed=12,
    )
    assert out["prop_board_status"] == "NO_MODEL"
    assert "home" in out["team_simulation_errors"]
    assert out["receiving_efficiency_regularization"].get("home") in (None, [])
    assert all(row["status"] == "NO_MODEL" for row in out["prop_markets"])

def test_missing_td_prerequisite_stays_local_and_does_not_poison_other_team():
    paths = [{"home_score": 20, "away_score": 24} for _ in range(80)]
    out = price_score_count_props_from_paths(
        game_id="G",
        score_paths=paths,
        prop_requests=[
            {
                "team": "home",
                "player": "NO_WR",
                "market": "anytime_tds",
                "selection": "over",
                "line": 0.5,
            },
            {
                "team": "away",
                "player": "ATL_WR",
                "market": "receiving_yards",
                "selection": "over",
                "line": 40.5,
            },
        ],
        home_model=None,
        away_model=_team("ATL"),
        scoring_prior=None,
        seed=13,
    )
    home_td, away_recv = out["prop_markets"]
    assert home_td["status"] == "NO_MODEL"
    assert home_td["reason"] == "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
    assert away_recv["status"] == "PRICED_RESEARCH"
    assert out["prop_board_status"] == "AVAILABLE"
    assert out["prop_board_error"] is None
    assert out["team_simulation_errors"] == {}

