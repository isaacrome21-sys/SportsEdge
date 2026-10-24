"""Tests for CFB starting-QB intake."""
from sportsedge.cfb_starting_qb_intake import from_source_rows, best_for_team


def test_non_mapping_rows_skipped():
    rows = [None, "bad", 42, {"team": "Alabama", "source": "OFFICIAL_TEAM_OR_CONFERENCE", "starter_name": "Milroe"}]
    out = from_source_rows(rows)
    assert len(out) == 1
    assert out[0].starter_name == "Milroe"
    assert out[0].play_authority is False
    assert out[0].promotion_authority is False


def test_empty_and_none_safe():
    assert from_source_rows([]) == []
    assert from_source_rows(None) == []  # type: ignore


def test_best_for_team_picks_highest():
    rows = [
        {"team": "Alabama", "source": "PROJECTED_OR_OR_LISTED", "starter_name": "Backup"},
        {"team": "Alabama", "source": "OFFICIAL_TEAM_OR_CONFERENCE", "starter_name": "Milroe", "source_url": "https://example.com"},
    ]
    best = best_for_team(rows, "Alabama")
    assert best is not None
    assert best.starter_name == "Milroe"
    assert best.play_authority is False
