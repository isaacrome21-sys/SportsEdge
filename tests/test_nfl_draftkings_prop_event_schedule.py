import pytest

from sportsedge.sports.nfl.draftkings_prop_event_schedule import (
    DraftKingsNFLEventScheduleError,
    parse_nfl_event_starts,
)


def test_parse_nfl_event_starts_binds_provider_ids_to_utc():
    payload = {
        "events": [
            {"id": 101, "startDate": "2026-09-13T17:00:00Z"},
            {"id": "102", "startTime": "2026-09-13T20:25:00+00:00"},
        ]
    }
    out = parse_nfl_event_starts(payload)
    assert out == {
        "101": "2026-09-13T17:00:00+00:00",
        "102": "2026-09-13T20:25:00+00:00",
    }


def test_parse_nfl_event_starts_skips_event_without_start_instead_of_guessing():
    out = parse_nfl_event_starts({"events": [{"id": 101}, {"id": 102, "startDate": "2026-09-13T17:00:00Z"}]})
    assert out == {"102": "2026-09-13T17:00:00+00:00"}


def test_parse_nfl_event_starts_rejects_naive_timestamp():
    with pytest.raises(DraftKingsNFLEventScheduleError, match="DK_NFL_EVENT_START_NAIVE"):
        parse_nfl_event_starts({"events": [{"id": 101, "startDate": "2026-09-13T17:00:00"}]})
