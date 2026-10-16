"""As-of reader: lag rules, final-report bound, PIT typing of snaps."""

from sportsedge.participation.archive import ParticipationArchive
from sportsedge.participation.reader import AsOfReader
from sportsedge.participation.schema import (
    AVAIL_FORWARD_ONLY,
    AVAIL_HISTORICAL,
    AVAIL_RETROSPECTIVE,
    BASIS_CAPTURE_TIMESTAMP,
    BASIS_COMPLETION_WINDOW,
    BASIS_FINAL_REPORT_RULE,
    BASIS_PRIOR_WEEK_LAG,
    REJ_NOT_YET_AVAILABLE,
    REJ_SAME_GAME_SNAPS_FEATURE,
    SIGNAL_DEPTH_CHART,
    SIGNAL_INACTIVE,
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_ROSTER_STATUS,
    SIGNAL_SNAP_ACTUAL,
    TIMING_CADENCE,
    USE_PREGAME_FEATURE,
    USE_TRAINING_TARGET,
    ParticipationRecord,
)

GSIS = "00-0030000"


def _designation(week=5, bound="2026-10-02T04:59:59Z", captured="2026-10-01T12:00:00Z"):
    return ParticipationRecord(
        signal_type=SIGNAL_INJURY_DESIGNATION, source_signal="S3", season=2026,
        week=week, team="BUF", captured_at_utc=captured,
        available_from_utc=bound, availability_class=AVAIL_HISTORICAL,
        availability_basis=BASIS_FINAL_REPORT_RULE, timing_evidence=TIMING_CADENCE,
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        gsis_id=GSIS, payload={"designation": "Questionable"})


def _roster(week, bound):
    return ParticipationRecord(
        signal_type=SIGNAL_ROSTER_STATUS, source_signal="S5", season=2026,
        week=week, team="BUF", captured_at_utc="2026-10-01T12:00:00Z",
        available_from_utc=bound, availability_class=AVAIL_HISTORICAL,
        availability_basis=BASIS_PRIOR_WEEK_LAG, timing_evidence=TIMING_CADENCE,
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        gsis_id=GSIS, payload={"status": "RES"})


def _depth(week, rank, bound, gsis="00-0031111"):
    return ParticipationRecord(
        signal_type=SIGNAL_DEPTH_CHART, source_signal="S6", season=2026,
        week=week, team="BUF", captured_at_utc="2026-10-01T12:00:00Z",
        available_from_utc=bound, availability_class=AVAIL_HISTORICAL,
        availability_basis=BASIS_PRIOR_WEEK_LAG, timing_evidence=TIMING_CADENCE,
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        gsis_id=gsis, position="QB", payload={"depth_rank": rank})


def _snaps(game_id, week, bound):
    return ParticipationRecord(
        signal_type=SIGNAL_SNAP_ACTUAL, source_signal="S9", season=2026,
        week=week, team="BUF", captured_at_utc="2026-10-01T12:00:00Z",
        available_from_utc=bound, availability_class=AVAIL_RETROSPECTIVE,
        availability_basis=BASIS_COMPLETION_WINDOW, timing_evidence="NONE",
        permitted_uses=[USE_TRAINING_TARGET], source_name="test",
        game_id=game_id, gsis_id=GSIS, payload={"offense_snaps": 60})


def _reader(tmp_path, records):
    arc = ParticipationArchive(tmp_path)
    for rec in records:
        arc.append_record(rec)
    return AsOfReader(arc)


def test_designation_hidden_before_final_report_bound(tmp_path):
    reader = _reader(tmp_path, [_designation()])
    early = reader.designation_for(GSIS, 2026, 5, "2026-10-01T12:00:00Z")
    assert early["status"] == "UNAVAILABLE"
    assert early["reason"] == REJ_NOT_YET_AVAILABLE
    late = reader.designation_for(GSIS, 2026, 5, "2026-10-03T00:00:00Z")
    assert late["status"] == "OK"
    assert late["record"].payload["designation"] == "Questionable"


def test_roster_prior_week_rule_defense_in_depth(tmp_path):
    # A week-5 snapshot may NEVER serve a week-5 game, even with an as_of
    # far in the future (its in-week compilation time is unknown).
    reader = _reader(tmp_path, [_roster(week=5, bound="2026-10-07T12:00:00Z")])
    ans = reader.roster_status_for(GSIS, 2026, 5, "2027-01-01T00:00:00Z")
    assert ans["status"] == "UNAVAILABLE"
    # ...but it serves week 6 once its bound has passed.
    ans6 = reader.roster_status_for(GSIS, 2026, 6, "2026-10-08T00:00:00Z")
    assert ans6["status"] == "OK"
    assert ans6["record"].payload["status"] == "RES"
    # ...and not before the bound.
    early6 = reader.roster_status_for(GSIS, 2026, 6, "2026-10-06T00:00:00Z")
    assert early6["status"] == "UNAVAILABLE"


def test_depth_chart_prior_week_only(tmp_path):
    reader = _reader(tmp_path, [_depth(week=5, rank=2, bound="2026-10-07T12:00:00Z")])
    same_week = reader.depth_chart_qb_for("BUF", 2026, 5, 2, "2027-01-01T00:00:00Z")
    assert same_week["status"] == "UNAVAILABLE"
    next_week = reader.depth_chart_qb_for("BUF", 2026, 6, 2, "2026-10-08T00:00:00Z")
    assert next_week["status"] == "OK"


def test_same_game_snaps_refused_as_features(tmp_path):
    reader = _reader(tmp_path, [_snaps("G1", 4, "2026-09-28T05:00:00Z")])
    ans = reader.feature_snaps_for_game("G1", "2026-10-03T00:00:00Z")
    assert ans["status"] == "REFUSED"
    assert ans["reason"] == REJ_SAME_GAME_SNAPS_FEATURE
    # The same records are fine as labels.
    labels = reader.label_snaps_for_game("G1")
    assert labels["status"] == "OK" and len(labels["records"]) == 1


def test_prior_game_snaps_completion_bound(tmp_path):
    reader = _reader(tmp_path, [_snaps("G1", 4, "2026-09-28T05:00:00Z")])
    before = reader.prior_game_snaps("BUF", 2026, 5, "2026-09-27T00:00:00Z")
    assert before["status"] == "UNAVAILABLE"
    after = reader.prior_game_snaps("BUF", 2026, 5, "2026-09-29T00:00:00Z")
    assert after["status"] == "OK"


def test_inactive_visible_only_from_capture(tmp_path):
    rec = ParticipationRecord(
        signal_type=SIGNAL_INACTIVE, source_signal="S7", season=2026, week=5,
        team="BUF", captured_at_utc="2026-10-04T15:30:00Z",
        available_from_utc="2026-10-04T15:30:00Z",
        availability_class=AVAIL_FORWARD_ONLY,
        availability_basis=BASIS_CAPTURE_TIMESTAMP, timing_evidence="PER_RECORD_TIMESTAMP",
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        game_id="G9", kickoff_utc="2026-10-04T17:00:00Z",
        gsis_id=GSIS, payload={"inactive": True})
    reader = _reader(tmp_path, [rec])
    early = reader.inactive_for(GSIS, "G9", "2026-10-04T15:00:00Z")
    assert early["status"] == "UNAVAILABLE"
    late = reader.inactive_for(GSIS, "G9", "2026-10-04T16:00:00Z")
    assert late["status"] == "OK"


def test_superseding_correction_never_rewrites_prior_as_of(tmp_path):
    arc = ParticipationArchive(tmp_path)
    first_id = arc.append_record(_designation(captured="2026-10-01T12:00:00Z"))
    corrected = _designation(captured="2026-10-06T12:00:00Z")
    corrected.payload["designation"] = "Out"
    corrected.supersedes_record_id = first_id
    arc.append_record(corrected)
    reader = AsOfReader(arc)
    old = reader.designation_for(GSIS, 2026, 5, "2026-10-03T12:00:00Z")
    assert old["status"] == "OK"
    assert old["record"].payload["designation"] == "Questionable"
    new = reader.designation_for(GSIS, 2026, 5, "2026-10-07T12:00:00Z")
    assert new["status"] == "OK"
    assert new["record"].payload["designation"] == "Out"


def test_forward_revision_only_becomes_visible_at_capture(tmp_path):
    from copy import deepcopy
    first = ParticipationRecord(
        signal_type=SIGNAL_INACTIVE, source_signal="S7", season=2026, week=5,
        team="BUF", captured_at_utc="2026-10-04T15:30:00Z",
        available_from_utc="2026-10-04T15:30:00Z",
        availability_class=AVAIL_FORWARD_ONLY,
        availability_basis=BASIS_CAPTURE_TIMESTAMP, timing_evidence="PER_RECORD_TIMESTAMP",
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        game_id="G9", kickoff_utc="2026-10-04T17:00:00Z",
        gsis_id=GSIS, payload={"inactive": False})
    arc = ParticipationArchive(tmp_path)
    original_id = arc.append_record(first)
    later = deepcopy(first)
    later.captured_at_utc = later.available_from_utc = "2026-10-04T16:00:00Z"
    later.payload = {"inactive": True}
    later.record_id = None
    later.supersedes_record_id = original_id
    arc.append_record(later)
    reader = AsOfReader(arc)
    assert reader.inactive_for(GSIS, "G9", "2026-10-04T15:45:00Z")["record"].payload["inactive"] is False
    assert reader.inactive_for(GSIS, "G9", "2026-10-04T16:15:00Z")["record"].payload["inactive"] is True



def test_correction_captured_early_but_not_yet_available_retains_prior(tmp_path):
    archive = ParticipationArchive(tmp_path)
    old = _designation(bound="2026-10-02T04:59:59Z",
                       captured="2026-10-01T12:00:00Z")
    old_id = archive.append_record(old)
    correction = _designation(bound="2026-10-05T04:59:59Z",
                              captured="2026-10-03T12:00:00Z")
    correction.payload = {"designation": "Out"}
    correction.supersedes_record_id = old_id
    new_id = archive.append_record(correction)
    reader = AsOfReader(archive)
    before = reader.designation_for(GSIS, 2026, 5, "2026-10-04T00:00:00Z")
    assert before["status"] == "OK"
    assert before["record"].record_id == old_id
    after = reader.designation_for(GSIS, 2026, 5, "2026-10-06T00:00:00Z")
    assert after["record"].record_id == new_id
