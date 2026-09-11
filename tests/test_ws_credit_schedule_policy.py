from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PARKED = {
    ".github/workflows/archive-mlb-game-odds.yml",
    ".github/workflows/auto-mlb.yml",
    ".github/workflows/mlb-additional-pit-archive.yml",
    ".github/workflows/mlb-deadman.yml",
    ".github/workflows/mlb-v8-evidence.yml",
    ".github/workflows/mlb-v8-replay-backfill.yml",
    ".github/workflows/nfl-2026-line-capture.yml",
}

SCHEDULED_PAID = {
    ".github/workflows/football-nfl-forward-clv-collection.yml",
    ".github/workflows/ev-tracker.yml",
}


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_parked_paid_workflows_have_no_timer() -> None:
    for path in sorted(PARKED):
        text = _text(path)
        assert "workflow_dispatch:" in text, path
        assert "schedule:" not in text, path


def test_remaining_authorities_still_have_schedules() -> None:
    for path in sorted(SCHEDULED_PAID):
        assert "schedule:" in _text(path), path


def test_push_ci_cannot_spend_mlb_auto_credits() -> None:
    text = _text(".github/workflows/auto-mlb.yml")
    assert "if: github.event_name == 'workflow_dispatch'\n        env:" in text


def test_mlb_additional_paid_archive_is_dispatch_only() -> None:
    text = _text(".github/workflows/mlb-additional-pit-archive.yml")
    assert "archive:\n    if: github.event_name == 'workflow_dispatch'" in text


def test_projection_matches_workflow_authority() -> None:
    policy = json.loads(_text("config/odds_api_request_projection_v3.json"))
    assert set(policy["parked_dispatch_only_workflows"]) == PARKED
    assert set(policy["invariants"]["allowed_scheduled_paid_consumers"]) == SCHEDULED_PAID
    assert policy["invariants"]["mlb_scheduled_paid_workflows"] == 0
    assert policy["invariants"]["legacy_nfl_2026_line_capture_scheduled"] is False
    assert policy["credential_slots"]["provider_terms_status"].startswith("UNVERIFIED")


def test_projection_does_not_fabricate_ev_tracker_weekly_bound() -> None:
    tracker = json.loads(_text("config/odds_api_request_projection_v3.json"))["scheduled_consumers"]["ev_tracker"]
    assert tracker["worst_case_weekly_credits"] is None
    assert tracker["bound_status"] == "NOT_FINITE_FROM_STATIC_SCHEDULE_WITHOUT_A_WEEKLY_ACCEPTED_PLAY_CAP"
