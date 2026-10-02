import pytest

from sportsedge.fresh_window_preregistration import assert_window_not_scoreable, load_preregistration
from sportsedge.research_surface_guard import ResearchSurfaceError


def test_preregistration_is_closed_and_not_promotable():
    prereg = load_preregistration()
    assert prereg["state"] == "CLOSED_NO_SOURCES"
    assert prereg["scoring_allowed"] is False
    assert prereg["promotion_allowed"] is False
    assert 2025 in prereg["forbidden"]["seasons"]


def test_missing_sources_cannot_score():
    with pytest.raises(ResearchSurfaceError, match="FRESH_WINDOW_CLOSED_MISSING_SOURCES"):
        assert_window_not_scoreable({"pit_feature_snapshot": True}, season=2026)


def test_spent_2025_window_cannot_score_even_with_sources():
    sources = {
        "pit_feature_snapshot": True,
        "paired_pregame_quotes": True,
        "same_book_pregame_close": True,
        "settlement": True,
    }
    with pytest.raises(ResearchSurfaceError, match="SPENT_TECHNICAL_FAILURE"):
        assert_window_not_scoreable(sources, season=2025, window_id="NFL_PROP_USAGE_V1_2025")


def test_complete_sources_still_do_not_open_the_window():
    sources = {
        "pit_feature_snapshot": True,
        "paired_pregame_quotes": True,
        "same_book_pregame_close": True,
        "settlement": True,
    }
    with pytest.raises(ResearchSurfaceError, match="FRESH_WINDOW_DECLARED_BUT_NOT_OPEN"):
        assert_window_not_scoreable(sources, season=2026, window_id="FRESH_PROP_TEAM_TOTAL_WINDOW_V1")
