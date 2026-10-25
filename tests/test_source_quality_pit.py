from sportsedge.source_quality import assess_evidence


BASE = {
    "source": "official-league-report",
    "game_id": "game-123",
    "captured_at": "2026-10-24T17:00:00-05:00",
    "status": "confirmed",
    "license": "permitted",
}
DECISION = "2026-10-24T18:00:00-05:00"


def test_confirmed_predecision_evidence():
    assert assess_evidence(BASE, DECISION, require_confirmed=True, commercial_use=True) == ()


def test_postdecision_capture_is_rejected():
    assert "POST_DECISION_EVIDENCE" in assess_evidence(
        {**BASE, "captured_at": "2026-10-24T18:01:00-05:00"}, DECISION
    )


def test_naive_and_invalid_timestamps_fail_closed():
    assert "INVALID_CAPTURE_TIME" in assess_evidence({**BASE, "captured_at": "2026-10-24T17:00:00"}, DECISION)
    assert "INVALID_DECISION_TIME" in assess_evidence(BASE, "bad")


def test_projection_is_not_confirmation():
    assert "NOT_CONFIRMED" in assess_evidence({**BASE, "status": "projected"}, DECISION, require_confirmed=True)


def test_research_license_not_commercially_approved():
    assert "COMMERCIAL_LICENSE_NOT_VERIFIED" in assess_evidence(
        {**BASE, "license": "research_only"}, DECISION, commercial_use=True
    )


def test_missing_metadata_fails_closed():
    result = assess_evidence({}, DECISION, require_confirmed=True, commercial_use=True)
    assert "MISSING_SOURCE" in result
    assert "MISSING_CAPTURED_AT" in result
    assert "MISSING_LICENSE" in result


def test_timezones_compare_by_instant():
    assert assess_evidence({**BASE, "captured_at": "2026-10-24T22:00:00Z"}, DECISION) == ()
