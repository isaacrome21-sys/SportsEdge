import json
from pathlib import Path

from sportsedge.engine_registry import engine_registry
from sportsedge.mlb_full_research_card import ALL_CARD_MARKETS, simulate_mlb_all_markets

ROOT = Path(__file__).resolve().parents[1]


def _pitcher(k, outs, er, hits, walks):
    return {
        "strikeouts": k,
        "outs": outs,
        "earned_runs": er,
        "hits_allowed": hits,
        "walks_allowed": walks,
    }


def _batter(hits, singles, doubles, triples, home_runs, rbi, runs, stolen, walks, strikeouts):
    return {
        "plate_appearances": 4,
        "hits": hits,
        "singles": singles,
        "doubles": doubles,
        "triples": triples,
        "home_runs": home_runs,
        "total_bases": singles + 2 * doubles + 3 * triples + 4 * home_runs,
        "rbi": rbi,
        "runs": runs,
        "stolen_bases": stolen,
        "walks": walks,
        "strikeouts": strikeouts,
        "extra_base_hits": doubles + triples + home_runs,
    }


def test_catalog_covers_registered_side_total_and_prop_engines():
    surface = json.loads((ROOT / "config/mlb_research_market_surface_v1.json").read_text())
    assert set(surface["markets"]) == set(ALL_CARD_MARKETS)
    assert set(ALL_CARD_MARKETS) <= set(engine_registry())
    assert surface["governance"]["promotion_authority"] is False
    assert surface["governance"]["official_authority"] is False


def test_one_simulation_prices_sides_totals_and_props_and_fails_closed():
    pitchers = {
        "away-p": [_pitcher(k, 18, 2, 5, 1) for k in range(4, 9)],
        "home-p": [_pitcher(k, 15, 4, 7, 3) for k in range(1, 6)],
    }
    batters = {
        "b1": [_batter(1, 1, 0, 0, 0, 0, 0, 0, 0, 1) for _ in range(5)],
    }
    f5 = {
        "away_f5_runs_for": [0, 1, 2, 0, 1, 3, 1, 0, 2, 1],
        "away_f5_runs_against": [1, 0, 1, 2, 0, 1, 1, 2, 0, 1],
        "home_f5_runs_for": [2, 1, 0, 3, 1, 1, 0, 2, 1, 1],
        "home_f5_runs_against": [0, 1, 1, 0, 2, 1, 1, 0, 1, 2],
    }
    card = simulate_mlb_all_markets(
        game_id="away@home",
        away_mean_runs=4.1,
        home_mean_runs=4.4,
        feature_source_hash="feature-hash",
        simulations=1000,
        pitcher_pools=pitchers,
        batter_pools=batters,
        f5_features=f5,
        selections=[
            {"selection_id": "ml", "market": "MONEYLINE", "side": "HOME", "line": 0},
            {"selection_id": "rl", "market": "RUN_LINE", "side": "HOME", "line": -1.5},
            {"selection_id": "tot", "market": "TOTALS", "side": "OVER", "line": 8.5},
            {"selection_id": "tt", "market": "TEAM_TOTALS", "team_side": "HOME", "side": "OVER", "line": 4.5},
            {"selection_id": "f5ml", "market": "F5_MONEYLINE", "side": "HOME", "line": 0},
            {"selection_id": "f5tt", "market": "F5_TEAM_TOTALS", "team_side": "AWAY", "side": "UNDER", "line": 2.5},
            {"selection_id": "outs", "market": "PITCHER_OUTS", "pitcher_id": "away-p", "side": "OVER", "line": 17.5},
            {"selection_id": "hits", "market": "HITS", "batter_id": "b1", "side": "OVER", "line": 0.5},
            {"selection_id": "either", "market": "EITHER_PITCHER_ER", "pitcher_a_id": "away-p", "pitcher_b_id": "home-p", "side": "OVER", "line": 3.5},
            {"selection_id": "nrfi", "market": "NRFI", "side": "YES", "line": 0.5},
        ],
    )
    by_id = {row["selection_id"]: row for row in card["rows"]}
    assert card["summary"]["official_bets"] == 0
    assert card["summary"]["side_rows"] == 3
    assert card["summary"]["total_rows"] == 3
    assert card["summary"]["prop_rows"] == 4
    assert len({row["simulation_id"] for row in card["rows"]}) == 1
    assert by_id["ml"]["display_status"] == "LEAN"
    assert by_id["hits"]["display_status"] == "LEAN"
    assert by_id["hits"]["research_p"] == 1.0
    assert by_id["nrfi"]["display_status"] == "NO_MODEL"
    assert by_id["nrfi"]["research_p"] is None
    assert card["governance"]["promotion_authority"] is False
