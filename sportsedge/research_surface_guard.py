"""Fail-closed guard for research prices and the spent 2025 prop window.

This module does not promote a market or change production engine_state.
"""

from __future__ import annotations

SPENT_WINDOW_ID = "NFL_PROP_USAGE_V1_2025"
SPENT_SEASON = 2025
RESEARCH_LANES = frozenset({"RESEARCH", "LEAN", "NO_ENGINE", "NO_MODEL"})
PRODUCTION_LABELS = frozenset({"Model_P", "OFFICIAL", "Truth Gate", "DEPLOYED"})


class ResearchSurfaceError(ValueError):
    """Raised when a research price or spent window is treated as production evidence."""


def assert_fresh_window(record: dict) -> None:
    """Reject the spent 2025 prop V1 window and any 2025 reuse of that candidate."""
    window_id = record.get("window_id")
    season = record.get("season")
    if window_id == SPENT_WINDOW_ID or season == SPENT_SEASON:
        raise ResearchSurfaceError(
            "SPENT_TECHNICAL_FAILURE: NFL prop usage V1 2025 cannot be reused, retried, or retuned"
        )
    if record.get("feature_snapshot_before_quotes") is not True:
        raise ResearchSurfaceError("FEATURE_SNAPSHOT_REQUIRED before quotes")
    if record.get("two_sided") and record.get("paired_quotes") is not True:
        raise ResearchSurfaceError("PAIRED_QUOTES_REQUIRED")
    if record.get("same_book_close") is not True:
        raise ResearchSurfaceError("SAME_BOOK_CLOSE_REQUIRED")
    if record.get("decision_before_close_before_start") is not True:
        raise ResearchSurfaceError("PREGAME_DECISION_TO_PREGAME_CLOSE_REQUIRED")
    if record.get("market") == "team_total" and record.get("path_reconciles_to_game_total") is not True:
        raise ResearchSurfaceError("TEAM_TOTAL_PATH_CONSERVATION_REQUIRED")


def assert_research_not_production(record: dict) -> None:
    """Keep research, LEAN, NO_ENGINE, and NO_MODEL prices off the production surface."""
    lane = record.get("lane")
    label = record.get("label")
    if lane in RESEARCH_LANES and label in PRODUCTION_LABELS:
        raise ResearchSurfaceError(
            f"{lane} cannot be labeled {label}; production engine_state is unchanged"
        )
