from scripts.preflight_nfl_score_counts_sources import (
    assert_depth_schema,
    assert_required,
    forbidden_columns,
)


def test_forbidden_column_scan_finds_market_fields_only():
    cols = ["game_id", "posteam", "epa", "spread_line", "sportsbook_price"]
    assert forbidden_columns(cols) == ["sportsbook_price", "spread_line"]


def test_required_columns_accepts_complete_header():
    assert_required(
        ["season", "week", "home_team", "away_team"],
        ("season", "week", "home_team", "away_team"),
        "schedule",
    )


def test_legacy_depth_schema_requires_weekly_identity():
    assert_depth_schema(
        ["season", "week", "club_code", "gsis_id", "depth_team", "position"],
        2024,
        "depth_2024",
    )


def test_timestamped_2025_depth_schema_does_not_require_season_or_week():
    assert_depth_schema(
        ["dt", "team", "player_name", "gsis_id", "pos_abb", "pos_rank"],
        2025,
        "depth_2025",
    )


def test_timestamped_depth_schema_requires_asof_timestamp():
    try:
        assert_depth_schema(
            ["team", "player_name", "gsis_id", "pos_abb", "pos_rank"],
            2025,
            "depth_2025",
        )
    except ValueError as exc:
        assert "dt" in str(exc)
    else:
        raise AssertionError("timestamped depth schema must require dt")
