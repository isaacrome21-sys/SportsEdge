from copy import deepcopy

import pytest

from sportsedge.fresh_window_source_receipts import validate_fresh_window_source_receipts
from sportsedge.research_surface_guard import ResearchSurfaceError


CODE_SHA = "1" * 40
HASHES = {
    "pit_feature_snapshot": "a" * 64,
    "paired_pregame_quotes": "b" * 64,
    "same_book_pregame_close": "c" * 64,
    "settlement": "d" * 64,
}


def _bundle():
    common = {
        "window_id": "FRESH_PROP_TEAM_TOTAL_WINDOW_V1",
        "season": 2026,
        "game_id": "game-1",
        "market_id": "player-passing-yards:123:250.5",
        "candidate_code_sha": CODE_SHA,
    }
    return [
        {
            **common,
            "kind": "pit_feature_snapshot",
            "content_sha256": HASHES["pit_feature_snapshot"],
            "observed_at": "2026-10-04T15:00:00+00:00",
        },
        {
            **common,
            "kind": "paired_pregame_quotes",
            "content_sha256": HASHES["paired_pregame_quotes"],
            "observed_at": "2026-10-04T15:05:00+00:00",
            "decision_at": "2026-10-04T15:06:00+00:00",
            "event_start_at": "2026-10-04T17:00:00+00:00",
            "book": "draftkings",
            "paired": True,
            "sides": ["OVER", "UNDER"],
        },
        {
            **common,
            "kind": "same_book_pregame_close",
            "content_sha256": HASHES["same_book_pregame_close"],
            "observed_at": "2026-10-04T16:55:00+00:00",
            "event_start_at": "2026-10-04T17:00:00+00:00",
            "book": "draftkings",
        },
        {
            **common,
            "kind": "settlement",
            "content_sha256": HASHES["settlement"],
            "observed_at": "2026-10-04T21:00:00+00:00",
            "event_start_at": "2026-10-04T17:00:00+00:00",
        },
    ]


def test_missing_receipts_remain_closed_without_scoring():
    report = validate_fresh_window_source_receipts(_bundle()[:1])
    assert report["state"] == "CLOSED_MISSING_RECEIPTS"
    assert report["complete_receipts"] is False
    assert report["scoring_allowed"] is False
    assert report["promotion_allowed"] is False


def test_complete_receipts_still_do_not_open_or_score_window():
    report = validate_fresh_window_source_receipts(_bundle())
    assert report["state"] == "COMPLETE_RECEIPTS_WINDOW_STILL_CLOSED"
    assert report["complete_receipts"] is True
    assert report["ready_for_open_review"] is True
    assert report["automatic_open_allowed"] is False
    assert report["scoring_allowed"] is False
    assert report["promotion_allowed"] is False


def test_spent_2025_receipts_are_forbidden():
    rows = _bundle()
    for row in rows:
        row["season"] = 2025
    with pytest.raises(ResearchSurfaceError, match="SEASON_FORBIDDEN"):
        validate_fresh_window_source_receipts(rows)


def test_close_must_be_same_book_as_paired_quote():
    rows = _bundle()
    rows[2]["book"] = "otherbook"
    with pytest.raises(ResearchSurfaceError, match="SAME_BOOK_CLOSE_REQUIRED"):
        validate_fresh_window_source_receipts(rows)


def test_temporal_inversion_fails_closed():
    rows = _bundle()
    rows[2]["observed_at"] = "2026-10-04T15:04:00+00:00"
    with pytest.raises(ResearchSurfaceError, match="TEMPORAL_ORDER_INVALID"):
        validate_fresh_window_source_receipts(rows)


def test_identity_mismatch_fails_closed():
    rows = _bundle()
    rows[3]["market_id"] = "different-market"
    with pytest.raises(ResearchSurfaceError, match="IDENTITY_MISMATCH"):
        validate_fresh_window_source_receipts(rows)


def test_invalid_content_hash_fails_closed():
    rows = _bundle()
    rows[0]["content_sha256"] = "not-a-hash"
    with pytest.raises(ResearchSurfaceError, match="CONTENT_SHA256_INVALID"):
        validate_fresh_window_source_receipts(rows)
