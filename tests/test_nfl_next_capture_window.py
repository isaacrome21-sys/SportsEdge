from datetime import datetime, timezone

from scripts.nfl_next_capture_window import next_window


def test_final_window_is_derived_without_odds_provider():
    events = [{
        "id": "evt1", "commence_time": "2026-09-18T00:15:00Z",
        "away_team": "Away", "home_team": "Home",
        "schedule_source": "ESPN_PUBLIC_SCOREBOARD", "schedule_only": True,
    }]
    r = next_window(datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc), events)
    assert r["capture_kind"] == "FINAL"
    assert r["start_ct"].startswith("2026-09-17T18:45:00")
    assert r["deadline_ct"].startswith("2026-09-17T19:00:00")
    assert r["schedule_only"] is True


def test_schedule_source_never_claims_book_or_odds_authority():
    events = [{
        "id": "evt2", "commence_time": "2026-09-18T01:00:00Z",
        "away_team": "A", "home_team": "B",
        "schedule_source": "ESPN_PUBLIC_SCOREBOARD", "schedule_only": True,
    }]
    r = next_window(datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc), events)
    assert "book" not in r
    assert "odds" not in r
    assert "provider" not in r
