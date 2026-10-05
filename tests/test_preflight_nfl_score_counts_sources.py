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


def test_pbp_projection_drops_market_columns_and_keeps_model_inputs():
    from sportsedge.sports.nfl.score_counts_source_projection import project_pbp_row

    raw = {
        "game_id": "2025_01_A_B",
        "posteam": "A",
        "defteam": "B",
        "epa": 0.25,
        "spread_line": -3.5,
        "total_line": 47.5,
        "home_opening_kickoff": "A",
        "sportsbook_price": -110,
    }
    out = project_pbp_row(raw)
    assert out == {
        "game_id": "2025_01_A_B",
        "posteam": "A",
        "defteam": "B",
        "epa": 0.25,
    }
    assert not any("spread" in key or "total_line" in key or "opening" in key for key in out)
