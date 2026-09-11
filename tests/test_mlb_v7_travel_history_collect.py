from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from sportsedge.mlb_v7_travel_history import MLBV7TravelHistoryError
from sportsedge.mlb_v7_travel_history_collect import collect_history_slice


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _schedule(state="Final"):
    return {"dates": [{"date": "2025-04-01", "games": [{
        "gamePk": 777001,
        "gameDate": "2025-04-01T23:10:00Z",
        "officialDate": "2025-04-01",
        "gameType": "R",
        "status": {"abstractGameState": state},
        "venue": {"id": 30},
        "teams": {"away": {"team": {"id": 10}}, "home": {"team": {"id": 20}}},
    }]}]}


def _opener(url, timeout=30):
    parsed = urlparse(url)
    if parsed.path.endswith("/api/v1/schedule"):
        payload = _schedule()
    elif parsed.path.endswith("/feed/live/timestamps"):
        payload = ["20250401_231000", "20250402_031500"]
    elif parsed.path.endswith("/feed/live"):
        assert parse_qs(parsed.query)["timecode"] == ["20250402_031500"]
        payload = {"gameData": {"status": {"abstractGameState": "Final"}}}
    elif "/api/v1/venues/30" in parsed.path:
        payload = {"venues": [{
            "id": 30,
            "location": {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}},
            "timeZone": {"id": "America/Chicago"},
        }]}
    else:
        raise AssertionError(url)
    return _Response(json.dumps(payload).encode("utf-8"))


def test_slice_writes_hash_bound_evidence_without_attestation(tmp_path) -> None:
    report = collect_history_slice(
        "2025-04-01", "2025-04-01", Path(tmp_path), opener=_opener,
        retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    assert report["state"] == "PASS_SOURCE_SLICE"
    assert report["schedule_game_count"] == 1
    assert report["verified_game_count"] == 1
    assert report["team_row_count"] == 2
    assert report["venue_count"] == 1
    assert report["attestation_written"] is False
    assert report["source_readiness_authority"] is False
    assert report["candidate_training_allowed"] is False
    for item in report["evidence"].values():
        path = Path(tmp_path) / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_nonfinal_historical_schedule_row_blocks_slice(tmp_path) -> None:
    def opener(url, timeout=30):
        parsed = urlparse(url)
        if parsed.path.endswith("/api/v1/schedule"):
            return _Response(json.dumps(_schedule("Preview")).encode("utf-8"))
        raise AssertionError("non-final schedule row must not trigger game evidence requests")

    report = collect_history_slice(
        "2025-04-01", "2025-04-01", Path(tmp_path), opener=opener,
        retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    assert report["state"] == "BLOCKED_SOURCE_SLICE"
    assert report["verified_game_count"] == 0
    assert report["failures"][0]["reason"] == "HISTORICAL_GAME_NOT_FINAL:Preview"
    assert "SLICE_SOURCE_INCOMPLETE" in report["blockers"]


def test_range_is_hard_bounded(tmp_path) -> None:
    with pytest.raises(MLBV7TravelHistoryError, match="DATE_RANGE_EXCEEDS_MAX_DAYS"):
        collect_history_slice("2025-01-01", "2025-03-01", Path(tmp_path), opener=_opener)


def test_full_snapshot_recheck_can_resolve_projection_only_status_mismatch(tmp_path) -> None:
    calls = []

    def opener(url, timeout=30):
        calls.append(url)
        parsed = urlparse(url)
        if parsed.path.endswith("/api/v1/schedule"):
            payload = _schedule()
        elif parsed.path.endswith("/feed/live/timestamps"):
            payload = ["20250401_231000", "20250402_031500"]
        elif parsed.path.endswith("/feed/live"):
            query = parse_qs(parsed.query)
            payload = {"gameData": {"status": {"abstractGameState": "Live" if "fields" in query else "Final"}}}
        elif "/api/v1/venues/30" in parsed.path:
            payload = {"venues": [{
                "id": 30,
                "location": {"defaultCoordinates": {"latitude": 41.0, "longitude": -87.0}},
                "timeZone": {"id": "America/Chicago"},
            }]}
        else:
            raise AssertionError(url)
        return _Response(json.dumps(payload).encode("utf-8"))

    report = collect_history_slice(
        "2025-04-01", "2025-04-01", Path(tmp_path), opener=opener,
        retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    assert report["state"] == "PASS_SOURCE_SLICE"
    live_calls = [url for url in calls if "/feed/live?" in url and not url.endswith("/timestamps")]
    assert len(live_calls) == 2
    assert "fields=" in live_calls[0]
    assert "fields=" not in live_calls[1]


def test_full_snapshot_recheck_still_blocks_nonfinal_terminal_state(tmp_path) -> None:
    def opener(url, timeout=30):
        parsed = urlparse(url)
        if parsed.path.endswith("/api/v1/schedule"):
            payload = _schedule()
        elif parsed.path.endswith("/feed/live/timestamps"):
            payload = ["20250401_231000", "20250402_031500"]
        elif parsed.path.endswith("/feed/live"):
            payload = {"gameData": {"status": {"abstractGameState": "Live"}}}
        else:
            raise AssertionError(url)
        return _Response(json.dumps(payload).encode("utf-8"))

    report = collect_history_slice(
        "2025-04-01", "2025-04-01", Path(tmp_path), opener=opener,
        retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    assert report["state"] == "BLOCKED_SOURCE_SLICE"
    assert report["failures"][0]["reason"] == "LAST_TIMECODE_NOT_FINAL:projected=Live:full=Live"
