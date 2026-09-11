from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from sportsedge.mlb_v7_travel_history import (
    MLBV7TravelHistoryError,
    extract_timecodes,
    normalize_final_game,
    parse_venue_reference,
    probe_one_final_game,
    timecode_to_utc_iso,
)


def _game(**overrides):
    row = {
        "game_id": 777001,
        "away_team_id": 10,
        "home_team_id": 20,
        "venue_id": 30,
        "game_start_time": "2025-04-01T23:10:00+00:00",
        "status": "Final",
        "official_date": "2025-04-01",
        "game_type": "R",
    }
    row.update(overrides)
    return row


def _final_snapshot(state="Final"):
    return {"gameData": {"status": {"abstractGameState": state}}}


def _venue():
    return {"venues": [{
        "id": 30,
        "location": {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}},
        "timeZone": {"id": "America/Chicago"},
    }]}


def _schedule():
    return {"dates": [{"date": "2025-04-01", "games": [{
        "gamePk": 777001,
        "gameDate": "2025-04-01T23:10:00Z",
        "officialDate": "2025-04-01",
        "gameType": "R",
        "status": {"abstractGameState": "Final"},
        "venue": {"id": 30},
        "teams": {"away": {"team": {"id": 10}}, "home": {"team": {"id": 20}}},
    }]}]}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _fake_opener(url, timeout=30):
    parsed = urlparse(url)
    if parsed.path.endswith("/api/v1/schedule"):
        payload = _schedule()
    elif parsed.path.endswith("/feed/live/timestamps"):
        payload = ["20250401_231000", "20250402_031500"]
    elif parsed.path.endswith("/feed/live"):
        assert parse_qs(parsed.query)["timecode"] == ["20250402_031500"]
        payload = _final_snapshot()
    elif "/api/v1/venues/30" in parsed.path:
        payload = _venue()
    else:
        raise AssertionError(url)
    return _Response(json.dumps(payload).encode("utf-8"))


def test_timecode_is_utc() -> None:
    assert timecode_to_utc_iso("20250402_031500") == "2025-04-02T03:15:00+00:00"


def test_timecodes_must_be_unique_and_monotonic() -> None:
    with pytest.raises(MLBV7TravelHistoryError, match="TIMECODE_ORDER_INVALID"):
        extract_timecodes(["20250402_031500", "20250401_231000"])
    with pytest.raises(MLBV7TravelHistoryError, match="TIMECODE_DUPLICATE"):
        extract_timecodes(["20250402_031500", "20250402_031500"])


def test_normalize_final_game_emits_two_team_rows() -> None:
    rows = normalize_final_game(
        _game(),
        ["20250401_231000", "20250402_031500"],
        _final_snapshot(),
    )
    assert len(rows) == 2
    assert {row.team_id for row in rows} == {10, 20}
    assert all(row.final_at == "2025-04-02T03:15:00+00:00" for row in rows)
    assert all(row.status == "Final" for row in rows)
    assert all(row.final_at_semantics == "LAST_HISTORICAL_TIMECODE_CONFIRMED_FINAL_UPPER_BOUND" for row in rows)


def test_missing_timestamps_fail_closed() -> None:
    with pytest.raises(MLBV7TravelHistoryError, match="FINAL_GAME_TIMESTAMPS_MISSING"):
        normalize_final_game(_game(), [], _final_snapshot())


def test_last_timecode_must_be_final() -> None:
    with pytest.raises(MLBV7TravelHistoryError, match="LAST_TIMECODE_NOT_FINAL"):
        normalize_final_game(_game(), ["20250402_031500"], _final_snapshot("Live"))


def test_final_at_cannot_precede_start() -> None:
    with pytest.raises(MLBV7TravelHistoryError, match="FINAL_AT_BEFORE_GAME_START"):
        normalize_final_game(_game(game_start_time="2025-04-02T04:00:00Z"), ["20250402_031500"], _final_snapshot())


def test_venue_reference_requires_coordinates_and_timezone() -> None:
    row = parse_venue_reference(_venue(), 30)
    assert row.venue_id == 30
    assert row.latitude == 41.0
    assert row.longitude == -87.0
    assert row.timezone == "America/Chicago"
    with pytest.raises(MLBV7TravelHistoryError, match="VENUE_COORDINATES_MISSING"):
        parse_venue_reference({"venues": [{"id": 30, "location": {}, "timeZone": {"id": "America/Chicago"}}]}, 30)
    with pytest.raises(MLBV7TravelHistoryError, match="VENUE_TIMEZONE_MISSING"):
        parse_venue_reference({"venues": [{"id": 30, "location": {"defaultCoordinates": {"latitude": 41, "longitude": -87}}, "timeZone": {}}]}, 30)


def test_probe_is_diagnostic_only_and_never_writes_attestation() -> None:
    report = probe_one_final_game("2025-04-01", opener=_fake_opener)
    assert report["state"] == "PASS_SOURCE_PROBE"
    assert report["promotion_authority"] is False
    assert report["candidate_training_allowed"] is False
    assert report["attestation_written"] is False
    assert report["historical_snapshot_status"] == "Final"
    assert report["team_row_count"] == 2
    assert report["venue"]["timezone"] == "America/Chicago"
    assert "FULL_2023_2025_COVERAGE_NOT_COLLECTED" in report["blockers"]
    assert "DECISION_TIME_BINDING_NOT_ATTESTED" in report["blockers"]
