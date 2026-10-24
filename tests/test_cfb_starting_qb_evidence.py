"""Tests for cfb_starting_qb_evidence."""
from datetime import datetime, timezone

from sportsedge.cfb_starting_qb_evidence import (
    SOURCE_WEIGHTS,
    merge_evidence,
    score_starting_qb,
)


def test_official_source_is_confirmed():
    row = score_starting_qb(
        team="Ohio State",
        source="OFFICIAL_TEAM_OR_CONFERENCE",
        starter_name="Julian Sayin",
        observed_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
    )
    assert row.confidence == 1.0
    assert row.confidence_label == "CONFIRMED"
    assert row.starter_name == "Julian Sayin"
    assert row.play_authority is False


def test_unknown_source_is_zero():
    row = score_starting_qb(team="Test", source="NO_SUCH_SOURCE", starter_name="Someone")
    assert row.confidence == 0.0
    assert row.confidence_label == "UNKNOWN"


def test_missing_name_zeros_confidence():
    row = score_starting_qb(team="Test", source="CFBDEPTH_OR_OURLADS")
    assert row.confidence == 0.0
    assert row.starter_name is None


def test_merge_picks_highest_confidence():
    low = score_starting_qb(
        team="Tennessee",
        source="PROJECTED_OR_OR_LISTED",
        starter_name="Faizon Brandon",
    )
    high = score_starting_qb(
        team="Tennessee",
        source="PRESS_BOX_OR_247_DEPTH_CHART",
        starter_name="George MacIntyre",
        observed_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
    )
    best = merge_evidence([low, high])
    assert best is not None
    assert best.starter_name == "George MacIntyre"
    assert best.confidence == SOURCE_WEIGHTS["PRESS_BOX_OR_247_DEPTH_CHART"]


def test_illinois_excluded_from_merge():
    row = score_starting_qb(
        team="Illinois",
        source="OFFICIAL_TEAM_OR_CONFERENCE",
        starter_name="Someone",
        illinois_college_team=True,
    )
    assert merge_evidence([row]) is None


def test_blank_name_zero_confidence():
    row = score_starting_qb(team="Alabama", source="OFFICIAL_TEAM_OR_CONFERENCE", starter_name="   ")
    assert row.starter_name is None
    assert row.confidence == 0.0
    assert row.confidence_label == "UNKNOWN"
    assert row.play_authority is False
    assert row.promotion_authority is False


def test_merge_forces_zero_authority():
    a = score_starting_qb(team="Alabama", source="OFFICIAL_TEAM_OR_CONFERENCE", starter_name="Milroe")
    b = score_starting_qb(team="Alabama", source="PROJECTED_OR_OR_LISTED", starter_name="Backup")
    best = merge_evidence([a, b])
    assert best is not None
    assert best.starter_name == "Milroe"
    assert best.play_authority is False
    assert best.promotion_authority is False
