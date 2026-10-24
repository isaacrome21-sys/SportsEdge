"""Tests for cfb_starting_qb_evidence."""
from datetime import datetime, timezone

from sportsedge.cfb_starting_qb_evidence import (
    SOURCE_WEIGHTS,
    is_illinois_college_team,
    merge_evidence,
    score_starting_qb,
)
from sportsedge.cfb_starting_qb_intake import best_for_team

T = datetime(2026, 10, 23, tzinfo=timezone.utc)
URL = "https://example.edu/football/depth-chart"


def test_official_verified_with_provenance_is_confirmed():
    row = score_starting_qb(team="Ohio State", source="OFFICIAL_TEAM_OR_CONFERENCE",
                            starter_name="Julian Sayin", observed_at=T,
                            source_url=URL, content_verified=True)
    assert row.confidence == 1.0
    assert row.confidence_label == "CONFIRMED"
    assert row.play_authority is False


def test_official_label_without_content_check_is_not_confirmed():
    row = score_starting_qb(team="Ohio State", source="OFFICIAL_TEAM_OR_CONFERENCE",
                            starter_name="Julian Sayin", observed_at=T, source_url=URL)
    assert row.confidence == SOURCE_WEIGHTS["PRESS_BOX_OR_247_DEPTH_CHART"]
    assert row.confidence_label != "CONFIRMED"
    assert "OFFICIAL_CONTENT_UNVERIFIED_CAPPED" in row.notes


def test_missing_url_or_time_caps_to_projection():
    row = score_starting_qb(team="Ohio State", source="OFFICIAL_TEAM_OR_CONFERENCE",
                            starter_name="Julian Sayin", content_verified=True)
    assert row.confidence == SOURCE_WEIGHTS["PROJECTED_OR_OR_LISTED"]
    assert "UNPROVENANCED_CAPPED" in row.notes


def test_unknown_source_is_zero():
    row = score_starting_qb(team="Test", source="NO_SUCH_SOURCE", starter_name="Someone")
    assert row.confidence == 0.0
    assert row.confidence_label == "UNKNOWN"


def test_missing_name_zeros_confidence():
    row = score_starting_qb(team="Test", source="CFBDEPTH_OR_OURLADS")
    assert row.confidence == 0.0
    assert row.starter_name is None


def test_merge_picks_highest_confidence():
    low = score_starting_qb(team="Tennessee", source="PROJECTED_OR_OR_LISTED",
                            starter_name="Faizon Brandon", game_id="g1")
    high = score_starting_qb(team="Tennessee", source="PRESS_BOX_OR_247_DEPTH_CHART",
                             starter_name="George MacIntyre", observed_at=T,
                             source_url=URL, game_id="g1")
    best = merge_evidence([low, high])
    assert best is not None and best.starter_name == "George MacIntyre"
    assert best.confidence == SOURCE_WEIGHTS["PRESS_BOX_OR_247_DEPTH_CHART"]


def test_merge_refuses_mixed_games():
    a = score_starting_qb(team="Tennessee", source="CFBDEPTH_OR_OURLADS",
                          starter_name="A", observed_at=T, source_url=URL, game_id="g1")
    b = score_starting_qb(team="Tennessee", source="CFBDEPTH_OR_OURLADS",
                          starter_name="A", observed_at=T, source_url=URL, game_id="g2")
    assert merge_evidence([a, b]) is None
    assert merge_evidence([a, b], game_id="g2").game_id == "g2"


def test_merge_refuses_mixed_teams_and_top_conflict():
    a = score_starting_qb(team="Iowa", source="CFBDEPTH_OR_OURLADS", starter_name="A",
                          observed_at=T, source_url=URL, game_id="g1")
    b = score_starting_qb(team="Minnesota", source="CFBDEPTH_OR_OURLADS", starter_name="B",
                          observed_at=T, source_url=URL, game_id="g1")
    c = score_starting_qb(team="Iowa", source="CFBDEPTH_OR_OURLADS", starter_name="C",
                          observed_at=T, source_url=URL, game_id="g1")
    assert merge_evidence([a, b]) is None
    assert merge_evidence([a, c]) is None
    assert merge_evidence([a, b], team="Iowa").starter_name == "A"


def test_illinois_derived_without_caller_flag():
    assert is_illinois_college_team("Northwestern")
    assert is_illinois_college_team("Northern Illinois")
    row = score_starting_qb(team="Rutgers", opponent="Northwestern",
                            source="CFBDEPTH_OR_OURLADS", starter_name="X",
                            observed_at=T, source_url=URL)
    assert row.illinois_college_team is True
    assert merge_evidence([row]) is None


def test_illinois_excluded_from_merge():
    row = score_starting_qb(team="Illinois", source="OFFICIAL_TEAM_OR_CONFERENCE",
                            starter_name="Someone")
    assert merge_evidence([row]) is None


def test_best_for_team_scopes_game():
    rows = [
        {"team": "Iowa", "source": "CFBDEPTH_OR_OURLADS", "starter_name": "Old",
         "game_id": "wk7", "observed_at": "2026-10-16T12:00:00Z", "source_url": URL},
        {"team": "Iowa", "source": "CFBDEPTH_OR_OURLADS", "starter_name": "New",
         "game_id": "wk8", "observed_at": "2026-10-23T12:00:00Z", "source_url": URL},
    ]
    assert best_for_team(rows, "Iowa") is None
    assert best_for_team(rows, "Iowa", game_id="wk8").starter_name == "New"
