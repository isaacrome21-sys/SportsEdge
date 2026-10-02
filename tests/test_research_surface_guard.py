import pytest

from sportsedge.research_surface_guard import (
    ResearchSurfaceError,
    assert_fresh_window,
    assert_research_not_production,
)


def _fresh(**overrides):
    record = {
        "window_id": "FRESH_PROP_TEAM_TOTAL_WINDOW_V1",
        "season": 2026,
        "feature_snapshot_before_quotes": True,
        "two_sided": True,
        "paired_quotes": True,
        "same_book_close": True,
        "decision_before_close_before_start": True,
    }
    record.update(overrides)
    return record


def test_spent_2025_window_cannot_be_reused():
    with pytest.raises(ResearchSurfaceError, match="SPENT_TECHNICAL_FAILURE"):
        assert_fresh_window(_fresh(window_id="NFL_PROP_USAGE_V1_2025", season=2026))


def test_2025_season_cannot_be_retuned():
    with pytest.raises(ResearchSurfaceError, match="SPENT_TECHNICAL_FAILURE"):
        assert_fresh_window(_fresh(season=2025))


def test_team_total_must_reconcile_to_game_path():
    with pytest.raises(ResearchSurfaceError, match="TEAM_TOTAL_PATH_CONSERVATION_REQUIRED"):
        assert_fresh_window(_fresh(market="team_total", path_reconciles_to_game_total=False))


def test_research_and_lean_cannot_become_model_p():
    for lane in ("RESEARCH", "LEAN", "NO_ENGINE", "NO_MODEL"):
        with pytest.raises(ResearchSurfaceError):
            assert_research_not_production({"lane": lane, "label": "Model_P"})


def test_fresh_research_record_is_admissible_as_research():
    assert_fresh_window(_fresh())
    assert_research_not_production({"lane": "RESEARCH", "label": "NOT Model_P"}) is None
