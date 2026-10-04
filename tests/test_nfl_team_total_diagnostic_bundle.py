from datetime import datetime, timezone
from unittest.mock import patch

from sportsedge.sports.nfl.team_total_diagnostic_bundle import (
    build_team_total_run_it_diagnostics,
)


NOW = datetime(2026, 10, 4, 16, 56, tzinfo=timezone.utc)


def _report():
    return {
        "results": [
            {
                "game_id": "g1",
                "provider_event_id": "e1",
                "distribution_sha256": "a" * 64,
            }
        ]
    }


def _handoff():
    return {
        "game_id": "g1",
        "distribution_sha256": "a" * 64,
    }


def _event():
    return {"id": "e1"}


def _diagnostic():
    return {
        "game_id": "g1",
        "rows": [
            {
                "game_id": "g1",
                "official_eligible": False,
                "bet_status": "BLOCKED",
            }
        ],
        "authority": {
            "official": False,
            "promotion": False,
        },
    }


def test_complete_game_is_diagnostic_only_and_never_enters_bettor_card():
    with patch(
        "sportsedge.sports.nfl.team_total_diagnostic_bundle.build_verified_team_total_diagnostics",
        return_value=_diagnostic(),
    ):
        out = build_team_total_run_it_diagnostics(
            report=_report(),
            handoffs=[_handoff()],
            provider_events=[_event()],
            now=NOW,
        )
    assert out["status"] == "DIAGNOSTICS_READY"
    assert out["diagnostic_game_count"] == 1
    assert out["bettor_card"] == []
    assert all(value is False for value in out["authority"].values())


def test_missing_handoff_is_visible_blocker_not_silent_skip():
    out = build_team_total_run_it_diagnostics(
        report=_report(),
        handoffs=[],
        provider_events=[_event()],
        now=NOW,
    )
    assert out["status"] == "BLOCKED"
    assert out["diagnostic_game_count"] == 0
    assert out["blocked_game_count"] == 1
    assert out["blockers"][0]["reason"] == "NFL_TEAM_TOTAL_HANDOFF_MISSING"
    assert out["bettor_card"] == []


def test_missing_provider_event_is_visible_blocker():
    out = build_team_total_run_it_diagnostics(
        report=_report(),
        handoffs=[_handoff()],
        provider_events=[],
        now=NOW,
    )
    assert out["status"] == "BLOCKED"
    assert out["blockers"][0]["reason"] == "NFL_TEAM_TOTAL_PROVIDER_EVENT_MISSING"


def test_bad_verified_diagnostic_becomes_blocker():
    with patch(
        "sportsedge.sports.nfl.team_total_diagnostic_bundle.build_verified_team_total_diagnostics",
        side_effect=ValueError("quote bad"),
    ):
        out = build_team_total_run_it_diagnostics(
            report=_report(),
            handoffs=[_handoff()],
            provider_events=[_event()],
            now=NOW,
        )
    assert out["status"] == "BLOCKED"
    assert out["blockers"][0]["reason"] == "quote bad"


def test_multiple_games_require_every_game_to_be_accounted_for():
    report = {
        "results": [
            {"game_id": "g1", "provider_event_id": "e1", "distribution_sha256": "a" * 64},
            {"game_id": "g2", "provider_event_id": "e2", "distribution_sha256": "b" * 64},
        ]
    }
    handoffs = [_handoff(), {"game_id": "g2", "distribution_sha256": "b" * 64}]
    events = [_event()]
    with patch(
        "sportsedge.sports.nfl.team_total_diagnostic_bundle.build_verified_team_total_diagnostics",
        return_value=_diagnostic(),
    ):
        out = build_team_total_run_it_diagnostics(
            report=report,
            handoffs=handoffs,
            provider_events=events,
            now=NOW,
        )
    assert out["status"] == "PARTIAL_DIAGNOSTICS"
    assert out["diagnostic_game_count"] == 1
    assert out["blocked_game_count"] == 1
    assert out["blockers"][0]["game_id"] == "g2"
    assert out["bettor_card"] == []
