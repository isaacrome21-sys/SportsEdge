from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.dfs.ownership_evidence import (
    OwnershipEvidenceError,
    build_realized_ownership_snapshot,
)


def _csv() -> bytes:
    return (
        "EntryId,EntryName,Lineup,Points\n"
        '1001,Isaac,"P Pitcher A (1) P Pitcher B (2) C Catcher A (3) 1B First A (4) 2B Second A (5) 3B Third A (6) SS Short A (7) OF Out A (8) OF Out B (9) OF Out C (10)",120.5\n'
        '1002,Field,"P Pitcher A (1) P Pitcher C (11) C Catcher B (12) 1B First B (13) 2B Second B (14) 3B Third B (15) SS Short B (16) OF Out D (17) OF Out E (18) OF Out F (19)",110.0\n'
    ).encode("utf-8")


def test_complete_entered_contest_produces_exact_realized_ownership() -> None:
    lock = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    captured = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    snapshot = build_realized_ownership_snapshot(
        _csv(),
        contest_id="777",
        our_entry_id="1001",
        slate_lock=lock,
        captured_at=captured,
        expected_field_size=2,
    )
    assert snapshot.entrant_count == 2
    assert snapshot.realized_ownership["1"] == 1.0
    assert snapshot.realized_ownership["2"] == 0.5
    assert snapshot.evidence_class == "RETROSPECTIVE_REALIZED_OWNERSHIP"
    assert snapshot.may_influence_same_slate_optimization is False
    assert len(snapshot.source_sha256) == 64


def test_export_must_contain_our_entry_and_complete_field() -> None:
    lock = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    captured = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(OwnershipEvidenceError, match="OUR_ENTRY_NOT_FOUND"):
        build_realized_ownership_snapshot(
            _csv(),
            contest_id="777",
            our_entry_id="9999",
            slate_lock=lock,
            captured_at=captured,
            expected_field_size=2,
        )
    with pytest.raises(OwnershipEvidenceError, match="FIELD_INCOMPLETE"):
        build_realized_ownership_snapshot(
            _csv(),
            contest_id="777",
            our_entry_id="1001",
            slate_lock=lock,
            captured_at=captured,
            expected_field_size=3,
        )


def test_realized_ownership_cannot_be_captured_prelock() -> None:
    lock = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    captured = datetime(2026, 9, 14, 4, 59, tzinfo=timezone.utc)
    with pytest.raises(OwnershipEvidenceError, match="CAPTURE_PRELOCK"):
        build_realized_ownership_snapshot(
            _csv(),
            contest_id="777",
            our_entry_id="1001",
            slate_lock=lock,
            captured_at=captured,
            expected_field_size=2,
        )
