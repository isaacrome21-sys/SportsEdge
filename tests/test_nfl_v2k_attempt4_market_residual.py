from sportsedge.sports.nfl import v2k_attempt4_validation as V4
from sportsedge.sports.nfl.v2k_attempt4_market_residual import (
    build_residual_rows,
    candidate_probability,
    choose_beta,
)


def _game(game_id, season, week, home, away, hs, as_, spread=3.0, total=44.0, odds=-110):
    return {
        "game_id": game_id,
        "season": season,
        "week": week,
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": as_,
        "_market": {
            "spread_line": spread,
            "total_line": total,
            "home_spread_odds": odds,
            "away_spread_odds": odds,
            "over_odds": odds,
            "under_odds": odds,
        },
    }


def test_zero_signal_is_exact_market_baseline():
    assert abs(candidate_probability(0.53, 0.0, beta=2.0, scale=13.5) - 0.53) < 1e-12


def test_same_week_results_cannot_leak_into_other_same_week_forecasts():
    schedule = {
        "g1": _game("g1", 2024, 1, "A", "B", 40, 10),
        "g2": _game("g2", 2024, 1, "C", "A", 20, 21),
        "g3": _game("g3", 2024, 2, "A", "D", 24, 20),
    }
    rows = build_residual_rows(schedule)
    by_id = {r["game_id"]: r for r in rows}
    assert by_id["g1"]["spread_signal"] == 0.0
    assert by_id["g2"]["spread_signal"] == 0.0
    assert by_id["g3"]["spread_signal"] != 0.0


def test_beta_selection_can_choose_market_only_when_residual_has_no_signal():
    rows = []
    for season in (2018, 2019, 2020):
        for i in range(20):
            rows.append({
                "season": season,
                "home_cover_outcome": i % 2,
                "base_home_cover_probability": 0.5,
                "spread_signal": 0.0,
            })
    assert choose_beta(rows, market="spread") == 0.0


def test_attempt4_frozen_identity_preflight_matches_branch_bytes():
    contract = V4.preflight()
    assert contract["candidate_family"] == "NFL_MARKET_ANCHORED_TEAM_RESIDUAL_G4"
    assert contract["attempt_budget"]["development_budget_units_used_before_attempt4"] == 3
