from sportsedge.sports.nhl.features import GoalieState
from sportsedge.sports.nhl.official_roster_source import (
    ROSTER_ENDPOINT,
    build_official_roster_receipt,
    verify_goalie_roster_identity,
)

import pytest


def _payload():
    return {
        "forwards": [{"id": 1, "firstName": {"default": "A"}, "lastName": {"default": "Forward"}, "positionCode": "C"}],
        "defensemen": [{"id": 2, "firstName": {"default": "A"}, "lastName": {"default": "Defense"}, "positionCode": "D"}],
        "goalies": [
            {"id": 30, "firstName": {"default": "Goalie"}, "lastName": {"default": "One"}, "positionCode": "G"},
            {"id": 31, "firstName": {"default": "Goalie"}, "lastName": {"default": "Two"}, "positionCode": "G"},
        ],
    }


def test_builds_pit_identity_receipt_without_starter_claim():
    out = build_official_roster_receipt(
        team="CHI",
        puck_drop="2026-10-03T00:00:00Z",
        captured_at="2026-10-02T20:00:00Z",
        payload=_payload(),
    )
    assert out["source_uri"] == ROSTER_ENDPOINT.format(team="CHI")
    assert out["goalie_ids"] == ("30", "31")
    assert out["starting_goalie_confirmed"] is False
    assert len(out["normalized_sha256"]) == 64


def test_verifies_goalie_identity_but_preserves_projected_status():
    receipt = build_official_roster_receipt(
        team="CHI", puck_drop="2026-10-03T00:00:00Z",
        captured_at="2026-10-02T20:00:00Z", payload=_payload(),
    )
    goalie = GoalieState(
        goalie_id="30", status="PROJECTED", save_pct=0.912,
        goals_saved_above_expected_per_60=0.15, sample_shots=500,
    )
    verified = verify_goalie_roster_identity(goalie, receipt)
    assert verified.status == "PROJECTED"


def test_rejects_goalie_not_on_official_roster():
    receipt = build_official_roster_receipt(
        team="CHI", puck_drop="2026-10-03T00:00:00Z",
        captured_at="2026-10-02T20:00:00Z", payload=_payload(),
    )
    goalie = GoalieState(
        goalie_id="99", status="PROJECTED", save_pct=0.900,
        goals_saved_above_expected_per_60=0.0, sample_shots=100,
    )
    with pytest.raises(ValueError, match="not present"):
        verify_goalie_roster_identity(goalie, receipt)


def test_rejects_post_puck_roster_capture():
    with pytest.raises(ValueError, match="predate puck drop"):
        build_official_roster_receipt(
            team="CHI", puck_drop="2026-10-03T00:00:00Z",
            captured_at="2026-10-03T00:00:00Z", payload=_payload(),
        )


def test_rejects_wrong_source_uri():
    with pytest.raises(ValueError, match="source URI mismatch"):
        build_official_roster_receipt(
            team="CHI", puck_drop="2026-10-03T00:00:00Z",
            captured_at="2026-10-02T20:00:00Z", payload=_payload(),
            source_uri="https://example.com/roster",
        )
