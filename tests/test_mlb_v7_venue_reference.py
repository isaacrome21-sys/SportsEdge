from __future__ import annotations

from sportsedge.mlb_v7_venue_reference import (
    build_venue_reference_report,
    build_venue_reference_rows,
    venue_ids_from_schedule_payloads,
)


def _schedule():
    return {
        "dates": [{
            "date": "2025-04-01",
            "games": [
                {
                    "gamePk": 1,
                    "gameDate": "2025-04-01T23:00:00Z",
                    "officialDate": "2025-04-01",
                    "gameType": "R",
                    "status": {"abstractGameState": "Final"},
                    "venue": {"id": 10},
                    "teams": {"away": {"team": {"id": 100}}, "home": {"team": {"id": 200}}},
                },
                {
                    "gamePk": 2,
                    "gameDate": "2025-04-01T18:00:00Z",
                    "officialDate": "2025-04-01",
                    "gameType": "S",
                    "status": {"abstractGameState": "Final"},
                    "venue": {"id": 99},
                    "teams": {"away": {"team": {"id": 100}}, "home": {"team": {"id": 200}}},
                },
            ],
        }]
    }


def _venue(venue_id: int):
    return {
        "venues": [{
            "id": venue_id,
            "location": {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}},
            "timeZone": {"id": "America/Chicago"},
        }]
    }


def test_discovers_only_final_modeled_game_venues() -> None:
    assert venue_ids_from_schedule_payloads([_schedule()]) == [10]


def test_complete_fixed_facts_are_ready_to_attest() -> None:
    ids = venue_ids_from_schedule_payloads([_schedule()])
    rows, failures = build_venue_reference_rows(ids, fetch_venue_payload=_venue, source_url_for_venue=lambda v: f"https://example/{v}")
    report = build_venue_reference_report(coverage_start="2023-01-01", coverage_end="2025-12-31", venue_ids=ids, rows=rows, failures=failures)
    assert report["state"] == "READY_TO_ATTEST"
    assert report["blockers"] == []
    assert report["resolved_venue_count"] == 1
    assert rows[0]["timezone"] == "America/Chicago"
    assert report["promotion_authority"] is False
    assert report["candidate_training_allowed"] is False


def test_missing_timezone_fails_closed() -> None:
    ids = [10]
    bad = _venue(10)
    bad["venues"][0].pop("timeZone")
    rows, failures = build_venue_reference_rows(ids, fetch_venue_payload=lambda _: bad)
    report = build_venue_reference_report(coverage_start="2023-01-01", coverage_end="2025-12-31", venue_ids=ids, rows=rows, failures=failures)
    assert report["state"] == "BLOCKED_SOURCE_ACQUISITION"
    assert report["blockers"] == ["VENUE_REFERENCE_INCOMPLETE"]
    assert report["missing_venue_ids"] == [10]
    assert "VENUE_TIMEZONE_MISSING" in failures[0]["reason"]
