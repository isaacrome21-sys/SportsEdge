"""Schema validation: forward-capture-only signals and PIT typing rules."""

import pytest

from sportsedge.participation.schema import (
    AVAIL_FORWARD_ONLY,
    AVAIL_HISTORICAL,
    AVAIL_RETROSPECTIVE,
    BASIS_CAPTURE_TIMESTAMP,
    BASIS_COMPLETION_WINDOW,
    BASIS_FINAL_REPORT_RULE,
    REJ_CAPTURE_AFTER_KICKOFF,
    REJ_FORWARD_ONLY_HISTORICAL,
    SIGNAL_INACTIVE,
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_REPORT_REVISION,
    SIGNAL_SNAP_ACTUAL,
    TIMING_CADENCE,
    USE_PREGAME_FEATURE,
    USE_TRAINING_TARGET,
    ParticipationRecord,
    RecordValidationError,
    validate_record,
)


def _record(**overrides):
    base = dict(
        signal_type=SIGNAL_INJURY_DESIGNATION,
        source_signal="S3",
        season=2026,
        week=5,
        team="BUF",
        captured_at_utc="2026-10-01T12:00:00Z",
        available_from_utc="2026-10-02T04:59:59Z",
        availability_class=AVAIL_HISTORICAL,
        availability_basis=BASIS_FINAL_REPORT_RULE,
        timing_evidence=TIMING_CADENCE,
        permitted_uses=[USE_PREGAME_FEATURE],
        source_name="test",
        gsis_id="00-0030000",
        payload={"designation": "Questionable"},
    )
    base.update(overrides)
    return ParticipationRecord(**base)


def test_valid_designation_record_passes():
    validate_record(_record())


def test_inactive_cannot_be_historical():
    rec = _record(signal_type=SIGNAL_INACTIVE, source_signal="S7",
                  availability_class=AVAIL_HISTORICAL)
    with pytest.raises(RecordValidationError) as exc:
        validate_record(rec)
    assert REJ_FORWARD_ONLY_HISTORICAL in str(exc.value)


def test_inactive_requires_capture_bound():
    rec = _record(signal_type=SIGNAL_INACTIVE, source_signal="S7",
                  availability_class=AVAIL_FORWARD_ONLY,
                  availability_basis=BASIS_CAPTURE_TIMESTAMP,
                  available_from_utc="2026-10-01T12:00:00Z",
                  kickoff_utc="2026-10-04T17:00:00Z")
    validate_record(rec)  # captured well before kickoff: fine


def test_inactive_captured_after_kickoff_refused():
    rec = _record(signal_type=SIGNAL_INACTIVE, source_signal="S7",
                  availability_class=AVAIL_FORWARD_ONLY,
                  availability_basis=BASIS_CAPTURE_TIMESTAMP,
                  captured_at_utc="2026-10-04T18:30:00Z",
                  available_from_utc="2026-10-04T18:30:00Z",
                  kickoff_utc="2026-10-04T17:00:00Z")
    with pytest.raises(RecordValidationError) as exc:
        validate_record(rec)
    assert REJ_CAPTURE_AFTER_KICKOFF in str(exc.value)


def test_report_revision_forward_only():
    rec = _record(signal_type=SIGNAL_REPORT_REVISION, source_signal="S8",
                  availability_class=AVAIL_RETROSPECTIVE,
                  availability_basis=BASIS_COMPLETION_WINDOW)
    with pytest.raises(RecordValidationError) as exc:
        validate_record(rec)
    assert REJ_FORWARD_ONLY_HISTORICAL in str(exc.value)


def test_snaps_cannot_claim_pregame_feature_use():
    rec = _record(signal_type=SIGNAL_SNAP_ACTUAL, source_signal="S9",
                  availability_class=AVAIL_RETROSPECTIVE,
                  availability_basis=BASIS_COMPLETION_WINDOW,
                  timing_evidence="NONE",
                  permitted_uses=[USE_PREGAME_FEATURE])
    with pytest.raises(RecordValidationError):
        validate_record(rec)


def test_snaps_as_training_target_pass():
    rec = _record(signal_type=SIGNAL_SNAP_ACTUAL, source_signal="S9",
                  availability_class=AVAIL_RETROSPECTIVE,
                  availability_basis=BASIS_COMPLETION_WINDOW,
                  timing_evidence="NONE",
                  permitted_uses=[USE_TRAINING_TARGET])
    validate_record(rec)


def test_historical_requires_bound():
    rec = _record(available_from_utc=None)
    with pytest.raises(RecordValidationError):
        validate_record(rec)
