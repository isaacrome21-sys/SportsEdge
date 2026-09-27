from datetime import datetime, timezone
import pytest

from sportsedge.sports.nba.availability import (
    NBAAvailabilitySnapshot,
    availability_digest,
    availability_status,
    latest_availability,
)

UTC = timezone.utc


def snap(player, status, hour, *, team="CHI", source="official"):
    return NBAAvailabilitySnapshot(
        player_id=player,
        team_id=team,
        status=status,
        observed_at=datetime(2026, 1, 2, hour, tzinfo=UTC),
        source=source,
        source_version="v1",
    )


def test_latest_availability_is_strictly_pit_safe():
    rows = [snap("p1", "QUESTIONABLE", 10), snap("p1", "OUT", 12)]
    assert availability_status(rows, player_id="p1", as_of=datetime(2026, 1, 2, 11, tzinfo=UTC)) == "QUESTIONABLE"
    assert availability_status(rows, player_id="p1", as_of=datetime(2026, 1, 2, 13, tzinfo=UTC)) == "OUT"
    # Equal-time news is not considered known yet.
    assert availability_status(rows, player_id="p1", as_of=datetime(2026, 1, 2, 12, tzinfo=UTC)) == "QUESTIONABLE"


def test_latest_availability_rejects_conflicting_same_time_status():
    rows = [snap("p1", "OUT", 12, source="a"), snap("p1", "AVAILABLE", 12, source="b")]
    with pytest.raises(ValueError, match="conflicting"):
        latest_availability(rows, as_of=datetime(2026, 1, 2, 13, tzinfo=UTC))


def test_missing_player_fails_closed():
    with pytest.raises(ValueError, match="no PIT-eligible"):
        availability_status([snap("p1", "OUT", 12)], player_id="p2", as_of=datetime(2026, 1, 2, 13, tzinfo=UTC))


def test_digest_is_order_independent_and_status_validated():
    a = snap("p1", "OUT", 12)
    b = snap("p2", "AVAILABLE", 11)
    assert availability_digest([a, b]) == availability_digest([b, a])
    bad = NBAAvailabilitySnapshot("p3", "CHI", "MAYBE", datetime(2026, 1, 2, 9, tzinfo=UTC), "official", "v1")
    with pytest.raises(ValueError, match="unsupported"):
        availability_digest([bad])
