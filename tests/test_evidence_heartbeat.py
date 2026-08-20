from datetime import datetime, timezone

import pytest

from sportsedge.evidence_heartbeat import LaneState, evaluate_lanes


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def test_both_lanes_stale_with_same_cutoff_is_shared_outage_signature():
    now = _dt('2026-08-20T13:00:00Z')
    lanes = [
        LaneState(name='NRFI_YRFI', last_durable_at=_dt('2026-08-17T16:07:00Z'), max_age_seconds=6 * 3600),
        LaneState(name='MLB_ODDS_ARCHIVE', last_durable_at=_dt('2026-08-17T23:59:00Z'), max_age_seconds=26 * 3600),
    ]

    report = evaluate_lanes(lanes, now=now, shared_cutoff_tolerance_seconds=12 * 3600)

    assert report.alert is True
    assert report.shared_outage_signature is True
    assert {lane.name for lane in report.stale_lanes} == {'NRFI_YRFI', 'MLB_ODDS_ARCHIVE'}


def test_one_fresh_lane_prevents_shared_outage_signature():
    now = _dt('2026-08-20T13:00:00Z')
    lanes = [
        LaneState(name='NRFI_YRFI', last_durable_at=_dt('2026-08-20T12:30:00Z'), max_age_seconds=6 * 3600),
        LaneState(name='MLB_ODDS_ARCHIVE', last_durable_at=_dt('2026-08-17T23:59:00Z'), max_age_seconds=26 * 3600),
    ]

    report = evaluate_lanes(lanes, now=now, shared_cutoff_tolerance_seconds=12 * 3600)

    assert report.alert is True
    assert report.shared_outage_signature is False
    assert [lane.name for lane in report.stale_lanes] == ['MLB_ODDS_ARCHIVE']


def test_future_timestamp_fails_closed():
    now = _dt('2026-08-20T13:00:00Z')
    lanes = [LaneState(name='NRFI_YRFI', last_durable_at=_dt('2026-08-20T14:00:00Z'), max_age_seconds=6 * 3600)]

    with pytest.raises(ValueError, match='FUTURE_DURABLE_TIMESTAMP'):
        evaluate_lanes(lanes, now=now)


def test_all_fresh_lanes_do_not_alert():
    now = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc)
    lanes = [
        LaneState(name='NRFI_YRFI', last_durable_at=_dt('2026-08-20T12:45:00Z'), max_age_seconds=6 * 3600),
        LaneState(name='MLB_ODDS_ARCHIVE', last_durable_at=_dt('2026-08-20T00:05:00Z'), max_age_seconds=26 * 3600),
    ]

    report = evaluate_lanes(lanes, now=now)

    assert report.alert is False
    assert report.shared_outage_signature is False
    assert report.stale_lanes == ()
