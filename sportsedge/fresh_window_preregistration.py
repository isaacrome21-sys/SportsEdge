"""Closed preregistration for the fresh prop and team-total window.

Scoring is refused until a new PIT feature snapshot, paired quotes, and
settlements exist. This module does not create those sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from sportsedge.research_surface_guard import SPENT_SEASON, SPENT_WINDOW_ID, ResearchSurfaceError

PREREG_PATH = Path(__file__).resolve().parents[1] / "config" / "fresh_window_preregistration_v1.json"
REQUIRED_SOURCES = (
    "pit_feature_snapshot",
    "paired_pregame_quotes",
    "same_book_pregame_close",
    "settlement",
)


def load_preregistration() -> dict:
    return json.loads(PREREG_PATH.read_text())


def assert_window_not_scoreable(sources: dict | None = None, season: int | None = None, window_id: str | None = None) -> None:
    """Refuse scoring while the preregistered window is closed or sources are missing."""
    prereg = load_preregistration()
    if prereg.get("scoring_allowed") is not False or prereg.get("state") != "CLOSED_NO_SOURCES":
        raise ResearchSurfaceError("PREREGISTRATION_NOT_CLOSED")
    if window_id == SPENT_WINDOW_ID or season == SPENT_SEASON:
        raise ResearchSurfaceError("SPENT_TECHNICAL_FAILURE: 2025 prop window is not scoreable")
    present = sources or {}
    missing = [name for name in REQUIRED_SOURCES if not present.get(name)]
    if missing:
        raise ResearchSurfaceError("FRESH_WINDOW_CLOSED_MISSING_SOURCES: " + ",".join(missing))
    raise ResearchSurfaceError("FRESH_WINDOW_DECLARED_BUT_NOT_OPEN")
