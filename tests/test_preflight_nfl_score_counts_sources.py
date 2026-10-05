from scripts.preflight_nfl_score_counts_sources import forbidden_columns, assert_required

def test_forbidden_column_scan_finds_market_fields_only():
    cols = ["game_id", "posteam", "epa", "spread_line", "sportsbook_price"]
    assert forbidden_columns(cols) == ["sportsbook_price", "spread_line"]

def test_required_columns_accepts_complete_header():
    assert_required(["season", "week", "home_team", "away_team"], ("season", "week", "home_team", "away_team"), "schedule")
