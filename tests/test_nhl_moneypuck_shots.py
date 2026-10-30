"""MoneyPuck listed ZIP import; offline fake source only, no HTTP/polling."""
import csv
import hashlib
import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nhl.moneypuck_shots import (
    MoneyPuckError, ingest_shot_zip, source_url,
)

FETCHED = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _zip(rows=None, *, header=None):
    rows = rows or [
        {"shotID": "1", "game_id": "2025020001", "team": "NYR", "event": "SHOT", "xGoal": "0.1"},
        {"shotID": "2", "game_id": "2025020001", "team": "BOS", "event": "GOAL", "xGoal": "0.25"},
        {"shotID": "3", "game_id": "2025020001", "team": "BOS", "event": "MISS", "xGoal": "0.05"},
    ]
    fields = header or ["shotID", "game_id", "team", "event", "xGoal"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("shots_2025.csv", buffer.getvalue())
    return output.getvalue()


def test_game_level_xg_receipt_is_provenance_bound_and_research_only():
    source = _zip()
    data = ingest_shot_zip(source, season_start=2025, fetched_at=FETCHED)
    assert data["source_url"] == source_url(2025)
    assert data["sha256"] == hashlib.sha256(source).hexdigest()
    assert data["shot_count"] == 3
    assert data["rows"] == [
        {"game_id": "2025020001", "team": "BOS", "shots_unblocked_attempts_excluding_blocked": 2,
         "goals_shot_events": 1, "xg": 0.3},
        {"game_id": "2025020001", "team": "NYR", "shots_unblocked_attempts_excluding_blocked": 1,
         "goals_shot_events": 0, "xg": 0.1},
    ]
    assert data["historical_pit"] is False
    assert data["pricing_input"] is False and data["play_eligible"] is False
    assert "NON_COMMERCIAL_ONLY" in data["license_scope"]
    assert data["attribution"] == "MoneyPuck.com"


@pytest.mark.parametrize("value, error", [
    (2006, "SEASON_UNLISTED"), (2026, "SEASON_UNLISTED"),
    (True, "SEASON_UNLISTED"),
])
def test_source_season_must_be_listed(value, error):
    with pytest.raises(MoneyPuckError, match=error):
        source_url(value)


@pytest.mark.parametrize("rows, error", [
    ([{"shotID": "1", "game_id": "2025020001", "team": "BOS", "event": "GOAL", "xGoal": "nan"}], "XG_RANGE_INVALID"),
    ([{"shotID": "1", "game_id": "2025020001", "team": "BOS", "event": "GOAL", "xGoal": "1.1"}], "XG_RANGE_INVALID"),
    ([{"shotID": "1", "game_id": "2025020001", "team": "BOS", "event": "BLOCK", "xGoal": "0.2"}], "TEAM_OR_EVENT_INVALID"),
    ([{"shotID": "1", "game_id": "2025020001", "team": "BOS", "event": "SHOT", "xGoal": "0.1"},
      {"shotID": "1", "game_id": "2025020001", "team": "NYR", "event": "SHOT", "xGoal": "0.1"}], "SHOT_ID_OR_GAME_ID_INVALID"),
])
def test_bad_rows_refuse_whole_archive(rows, error):
    with pytest.raises(MoneyPuckError, match=error):
        ingest_shot_zip(_zip(rows), season_start=2025, fetched_at=FETCHED)


def test_missing_columns_and_corrupt_zip_refused():
    with pytest.raises(MoneyPuckError, match="SHOT_COLUMNS_MISSING"):
        ingest_shot_zip(_zip(header=["shotID", "game_id", "team", "event"]),
                        season_start=2025, fetched_at=FETCHED)
    with pytest.raises(MoneyPuckError, match="ZIP_INVALID"):
        ingest_shot_zip(b"not-a-zip", season_start=2025, fetched_at=FETCHED)


def test_fetched_at_cannot_be_naive_or_future():
    with pytest.raises(MoneyPuckError, match="FETCH_TIME_OFFSET_REQUIRED"):
        ingest_shot_zip(_zip(), season_start=2025, fetched_at="2026-10-25T12:00:00")
    with pytest.raises(MoneyPuckError, match="FETCH_TIME_IN_FUTURE"):
        ingest_shot_zip(_zip(), season_start=2025, fetched_at=datetime.now(timezone.utc) + timedelta(days=1))
