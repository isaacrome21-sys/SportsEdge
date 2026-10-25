"""Owner ruling 2026-10-25: strict entry capture for CLV (fail closed).

Entry needs an offset-aware Captured time (never issue created_at); a claimed
capture later than the recording clock is refused; a pregame Captured that was
recorded after start is a backfill and ignored; entry == close is not CLV.
"""
from datetime import datetime, timezone

import pytest

from scripts.grade_mlb_card import CardRow
from scripts.mlb_card_clv import compute_clv
from sportsedge.line_snapshots import (
    SnapshotError,
    append_snapshot,
    build_snapshot,
    entry_and_close,
    load_snapshots,
)
from tests.test_mlb_card_clv import CLOSE, ENTRY, NO_CAPTURED, _feed, _issue
from tests.test_line_snapshots import ML, TITLE, body

START = "2026-10-25T00:00:00Z"
PICK = [CardRow(1, "Moneyline Home", -120, "ACTIONABLE")]


def _snap(root, captured, ml, picks, recorded):
    rec = build_snapshot(sport="mlb", issue_number=100, body=body(captured, ml), title=TITLE,
                         game={"game_pk": 1}, board=[], picks=picks, recorded_at=recorded)
    append_snapshot(rec, root)


def test_future_capture_vs_recording_clock_refused():
    with pytest.raises(SnapshotError):
        build_snapshot(sport="mlb", issue_number=1, body=body("2026-10-24T23:00:00Z", "+100 -120"),
                       title=TITLE, game={}, board=[], picks=[], recorded_at="2026-10-24T22:00:00Z")


@pytest.mark.parametrize("recorded", ["", "x", "2026-10-24T23:00:00"])
def test_missing_or_naive_recorded_at_refused(recorded):
    with pytest.raises(SnapshotError):
        build_snapshot(sport="mlb", issue_number=1, body=body("2026-10-24T22:00:00Z", "+100 -120"),
                       title=TITLE, game={}, board=[], picks=[], recorded_at=recorded)


def test_pregame_capture_recorded_after_start_is_ignored(tmp_path):
    _snap(tmp_path, "2026-10-24T22:20:00Z", "+100 -120", [ML], "2026-10-24T22:21:00Z")
    _snap(tmp_path, "2026-10-24T23:50:00Z", "+110 -130", [], "2026-10-25T00:05:00Z")  # backfill
    got = entry_and_close(load_snapshots("mlb", 100, tmp_path), "Moneyline Home", START)
    assert got.status == "NO_DISTINCT_CLOSE" and got.close is None


def test_entry_equal_close_is_not_clv(tmp_path):
    _snap(tmp_path, "2026-10-24T22:20:00Z", "+100 -120", [ML], "2026-10-24T22:21:00Z")
    out = compute_clv(issue_number=100, picks=PICK, feed=_feed(), entry_issue={},
                      snapshots=load_snapshots("mlb", 100, tmp_path))[0]
    assert out["clv_status"] == "NO_CLOSE_QUOTE" and out["clv_prob"] == ""


def test_tampered_snapshot_row_without_recorded_at_ignored(tmp_path):
    _snap(tmp_path, "2026-10-24T22:20:00Z", "+100 -120", [ML], "2026-10-24T22:21:00Z")
    snaps = load_snapshots("mlb", 100, tmp_path)
    forged = dict(snaps[0], captured_at="2026-10-24T23:50:00+00:00", recorded_at=None)
    got = entry_and_close(snaps + [forged], "Moneyline Home", START)
    assert got.status == "NO_DISTINCT_CLOSE"


def test_legacy_entry_never_uses_created_at():
    entry = _issue(100, None, ["ML +100 -120"], created="2026-10-24T22:00:00Z")
    out = compute_clv(issue_number=100, picks=PICK, feed=_feed(), entry_issue=entry,
                      other_issues=[CLOSE])[0]
    assert out["clv_status"] == "NO_ENTRY_CAPTURE" and out["clv_prob"] == ""


def test_legacy_future_close_ignored():
    now = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)  # before CLOSE's 23:50 capture
    out = compute_clv(issue_number=100, picks=PICK, feed=_feed(), entry_issue=ENTRY,
                      other_issues=[CLOSE, NO_CAPTURED], now=now)[0]
    assert out["clv_status"] == "NO_CLOSE_QUOTE"


def test_legacy_future_entry_refused():
    now = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)  # before ENTRY's 22:20 capture
    out = compute_clv(issue_number=100, picks=PICK, feed=_feed(), entry_issue=ENTRY,
                      other_issues=[CLOSE], now=now)[0]
    assert out["clv_status"] == "NO_ENTRY_CAPTURE"


@pytest.mark.parametrize("start", [None, "", "not-a-time", "2026-10-25T00:00:00"])
def test_missing_malformed_or_naive_first_pitch_fails_closed(start, tmp_path):
    feed = _feed()
    feed["gameData"]["datetime"]["dateTime"] = start
    legacy = compute_clv(issue_number=100, picks=PICK, feed=feed, entry_issue=ENTRY,
                         other_issues=[CLOSE])[0]
    snap = compute_clv(issue_number=100, picks=PICK, feed=feed, entry_issue={}, snapshots=[])[0]
    assert legacy["clv_status"] == snap["clv_status"] == "NO_FIRST_PITCH"


@pytest.mark.parametrize("ahead", [1, 119, 120, 121])
def test_capture_even_one_second_after_recording_refused(ahead):
    from datetime import timedelta as _td
    rec = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    cap = (rec + _td(seconds=ahead)).isoformat()
    with pytest.raises(SnapshotError):
        build_snapshot(sport="mlb", issue_number=1, body=body(cap, "+100 -120"), title=TITLE,
                       game={}, board=[], picks=[], recorded_at=rec.isoformat())


def test_capture_equal_to_recording_allowed():
    build_snapshot(sport="mlb", issue_number=1, body=body("2026-10-24T22:00:00+00:00", "+100 -120"),
                   title=TITLE, game={}, board=[], picks=[], recorded_at="2026-10-24T22:00:00+00:00")


def test_forged_row_capture_after_recording_ignored(tmp_path):
    _snap(tmp_path, "2026-10-24T22:20:00Z", "+100 -120", [ML], "2026-10-24T22:21:00Z")
    snaps = load_snapshots("mlb", 100, tmp_path)
    forged = dict(snaps[0], captured_at="2026-10-24T23:50:01+00:00", recorded_at="2026-10-24T23:50:00+00:00")
    assert entry_and_close(snaps + [forged], "Moneyline Home", START).status == "NO_DISTINCT_CLOSE"
