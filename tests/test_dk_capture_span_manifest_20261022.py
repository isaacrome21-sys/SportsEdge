"""Capture span two-tier policy: <=150 ladder, 151–300 PAPER only, >300 refused.

The quote age <=1800s is a separate real wall-clock guard, not enforced
by this inventory-only manifest. Failed/invalid captures never vanish.
"""
import pytest

from sportsedge.dk_capture_span_manifest import (
    QUOTE_MAX_AGE_S, SPAN_LIMIT_S, RESEARCH_SPAN_LIMIT_S,
    CaptureSpanManifestError,
    build_capture_span_manifest)

T0 = "2026-10-22T17:21:00-05:00"


def _rec(event_id="E1", start=T0, finish="2026-10-22T17:23:00-05:00", **kw):
    r = {"event_id": event_id, "capture_started_at": start,
         "capture_finished_at": finish}
    r.update(kw)
    return r


def test_limits_are_the_standing_ruling_values():
    assert SPAN_LIMIT_S == 150.0 and RESEARCH_SPAN_LIMIT_S == 300.0
    assert QUOTE_MAX_AGE_S == 1800.0


def test_two_games_within_limit_all_accepted():
    m = build_capture_span_manifest([
        _rec("E2", finish="2026-10-22T17:22:30-05:00"),
        _rec("E1"),
    ])
    assert m["status"] == "ALL_GAMES_WITHIN_LIMIT"
    assert m["accepted_event_ids"] == ["E1", "E2"]
    assert m["refused"] == []
    assert m["counts"] == {"games": 2, "ok": 2, "flagged_research": 0,
                           "refused_span": 0, "failed": 0}
    spans = {g["event_id"]: g["span_seconds"] for g in m["games"]}
    assert spans == {"E1": 120.0, "E2": 90.0}


def test_span_exactly_at_limit_is_ok():
    m = build_capture_span_manifest(
        [_rec(finish="2026-10-22T17:23:30-05:00")])
    assert m["games"][0]["span_seconds"] == 150.0
    assert m["games"][0]["status"] == "OK"
    assert m["games"][0]["ladder_eligible_by_span"] is True


def test_151_seconds_retained_paper_research_without_ladder_credit():
    m = build_capture_span_manifest(
        [_rec(finish="2026-10-22T17:23:31-05:00")])
    g = m["games"][0]
    assert g["span_seconds"] == 151.0 and g["status"] == "FLAGGED_RESEARCH"
    assert g["ladder_eligible_by_span"] is False
    assert g["paper_research_by_span"] is True
    assert m["accepted_event_ids"] == []
    assert m["research_event_ids"] == ["E1"]
    assert m["refused"] == []
    assert m["flagged"] == [
        {"event_id": "E1", "status": "FLAGGED_RESEARCH",
         "span_seconds": 151.0, "ladder_eligible": False}]
    assert m["status"] == "GAMES_FLAGGED_RESEARCH"
    assert m["counts"]["flagged_research"] == 1
    assert m["counts"]["refused_span"] == 0


@pytest.mark.parametrize("seconds,status", [
    (150, "OK"), (151, "FLAGGED_RESEARCH"),
    (300, "FLAGGED_RESEARCH"), (301, "REFUSED_SPAN"),
])
def test_exact_owner_span_boundaries(seconds, status):
    from datetime import timedelta, datetime
    start = datetime.fromisoformat(T0)
    end = (start + timedelta(seconds=seconds)).isoformat()
    m = build_capture_span_manifest([_rec(finish=end)])
    game = m["games"][0]
    assert game["span_seconds"] == float(seconds)
    assert game["status"] == status
    assert game["ladder_eligible_by_span"] is (seconds <= 150)
    assert (game["event_id"] in m["accepted_event_ids"]) is (seconds <= 150)
    assert (game["event_id"] in m["research_event_ids"]) is (150 < seconds <= 300)
    assert (game["event_id"] in [r["event_id"] for r in m["refused"]]) is (seconds > 300)


def test_manifest_does_not_pretend_to_verify_quote_wall_age():
    m = build_capture_span_manifest([_rec()])
    assert m["quote_max_age_seconds"] == 1800.0
    assert m["quote_age_enforced_here"] is False
    assert m["research_span_limit_seconds"] == 300.0


def test_failed_capture_listed_not_dropped():
    m = build_capture_span_manifest([
        _rec("E1"),
        _rec("E2", finish=None, failure_reason="BOARD_UNREACHABLE"),
    ])
    g2 = [g for g in m["games"] if g["event_id"] == "E2"][0]
    assert g2["status"] == "FAILED" and g2["span_seconds"] is None
    assert g2["failure_reason"] == "BOARD_UNREACHABLE"
    assert m["accepted_event_ids"] == ["E1"]
    assert m["counts"]["failed"] == 1 and m["status"] == "GAMES_REFUSED"


def test_span_is_per_game_not_slate_wide():
    # Research-tier slow game stays visible but cannot enter ladder.
    m = build_capture_span_manifest([
        _rec("FAST", finish="2026-10-22T17:21:45-05:00"),
        _rec("SLOW", finish="2026-10-22T17:26:00-05:00"),
        _rec("REFUSED", finish="2026-10-22T17:26:01-05:00"),
    ])
    assert m["accepted_event_ids"] == ["FAST"]
    assert m["research_event_ids"] == ["SLOW"]
    assert m["flagged"][0]["span_seconds"] == 300.0
    assert m["refused"][0]["event_id"] == "REFUSED"
    assert m["refused"][0]["span_seconds"] == 301.0
    assert m["counts"]["ok"] == m["counts"]["flagged_research"] == 1
    assert m["counts"]["refused_span"] == 1


def test_mixed_offsets_compute_the_same_span():
    m = build_capture_span_manifest([_rec(
        start="2026-10-22T22:21:00+00:00",
        finish="2026-10-22T17:23:00-05:00")])
    assert m["games"][0]["span_seconds"] == 120.0


def test_int_event_id_normalized_to_str():
    m = build_capture_span_manifest([_rec(12345)])
    assert m["games"][0]["event_id"] == "12345"
    assert m["accepted_event_ids"] == ["12345"]


@pytest.mark.parametrize("records,code", [
    ([], "NONEMPTY_SPAN_RECORDS_REQUIRED"),
    ("not-a-list", "NONEMPTY_SPAN_RECORDS_REQUIRED"),
    ([{"capture_started_at": T0, "capture_finished_at": None}],
     "EVENT_ID_REQUIRED"),
    ([_rec("")], "EVENT_ID_REQUIRED"),
    ([_rec(True)], "EVENT_ID_REQUIRED"),
    ([_rec(start=None)], "CAPTURE_TIMESTAMP_REQUIRED"),
    ([_rec(start="not-a-time")], "INVALID_CAPTURE_TIMESTAMP"),
    ([_rec(start="2026-10-22T17:21:00")], "TIMESTAMP_UTC_OFFSET_REQUIRED"),
    ([_rec(finish="2026-10-22T17:20:00-05:00")],
     "CAPTURE_SPAN_CHRONOLOGY_INVALID"),
    ([_rec(), _rec()], "DUPLICATE_EVENT_ID"),
    ([_rec(failure_reason="X")], "FAILURE_REASON_ON_FINISHED_CAPTURE"),
    ([_rec(finish=None, failure_reason="  ")], "FAILURE_REASON_INVALID"),
    ([_rec(extra_field=1)], "UNEXPECTED_SPAN_RECORD_FIELDS"),
])
def test_malformed_records_refused_by_name(records, code):
    with pytest.raises(CaptureSpanManifestError) as ei:
        build_capture_span_manifest(records)
    assert str(ei.value) == code
