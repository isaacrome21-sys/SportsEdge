"""Tests for sportsedge.live_state: parsing, validation, freshness.

Network-free: all fixtures are recorded under tests/fixtures/live/.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from sportsedge.live_state import (
    LIVE_STATE_STALENESS_THRESHOLD_SECONDS,
    FootballGameState,
    LiveStateError,
    MLBGameState,
    parse_espn_football_event,
    parse_mlb_live_feed,
)

FIXTURES = Path(__file__).parent / "fixtures" / "live"
NOW = datetime(2026, 10, 11, 23, 40, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fresh_feed(when=NOW):
    """Recorded feed with the provider timestamp stamped fresh."""
    import copy
    feed = copy.deepcopy(load("mlb_feed_final.json"))
    feed["metaData"]["timeStamp"] = when.strftime("%Y%m%d_%H%M%S")
    return feed


# ---------------------------------------------------------------------------
# MLB parsing (recorded final game: White Sox 0 @ Guardians 2)
# ---------------------------------------------------------------------------

def test_parse_mlb_final_feed():
    feed = load("mlb_feed_final.json")
    state = parse_mlb_live_feed(feed, retrieved_at=NOW, game_pk=849831)
    assert state.game_pk == 849831
    assert state.status == "FINAL"
    assert (state.away_team, state.home_team) == ("Chicago White Sox", "Cleveland Guardians")
    assert (state.away_score, state.home_score) == (0, 2)
    assert state.inning == 9
    assert state.half == "top"
    assert state.kickoff == datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
    assert not state.is_live()


def test_mlb_freshness_threshold_is_60s():
    assert LIVE_STATE_STALENESS_THRESHOLD_SECONDS == 60


def test_mlb_stale_state_detected():
    old = NOW - timedelta(seconds=61)
    state = parse_mlb_live_feed(fresh_feed(old), retrieved_at=old,
                                game_pk=849831)
    assert not state.is_fresh(NOW)
    fresh = parse_mlb_live_feed(
        fresh_feed(NOW - timedelta(seconds=59)),
        retrieved_at=NOW - timedelta(seconds=59), game_pk=849831)
    assert fresh.is_fresh(NOW)


def test_mlb_provider_timestamp_staleness():
    # A provider serving a cached/old snapshot is stale even if we just
    # fetched it.
    state = parse_mlb_live_feed(
        fresh_feed(NOW - timedelta(seconds=61)), retrieved_at=NOW,
        game_pk=849831)
    assert not state.is_fresh(NOW)
    reason = state.staleness_reason(NOW)
    assert reason is not None and "provider_timestamp" in reason


def test_mlb_future_observed_at_is_stale():
    state = parse_mlb_live_feed(fresh_feed(NOW), retrieved_at=NOW + timedelta(seconds=5),
                                game_pk=849831)
    assert not state.is_fresh(NOW)


def test_mlb_feed_empty_fails_closed():
    with pytest.raises(LiveStateError):
        parse_mlb_live_feed({}, retrieved_at=NOW)


def test_mlb_bad_game_pk_fails_closed():
    feed = load("mlb_feed_final.json")
    with pytest.raises(LiveStateError):
        parse_mlb_live_feed(feed, retrieved_at=NOW, game_pk=0)


def test_mlb_state_validation_rejects_implausible():
    feed = load("mlb_feed_final.json")
    state = parse_mlb_live_feed(feed, retrieved_at=NOW, game_pk=849831)
    bad = MLBGameState(**{**state.__dict__, "outs": 9})
    with pytest.raises(LiveStateError):
        bad.validate()


# ---------------------------------------------------------------------------
# NFL parsing (recorded live game: 49ers @ Seahawks, Q4 1:50)
# ---------------------------------------------------------------------------

def test_parse_nfl_live_event():
    event = load("nfl_live_event.json")
    state = parse_espn_football_event(event, sport="NFL", retrieved_at=NOW)
    assert state.status == "LIVE"
    assert state.is_live()
    assert state.event_id == "401872992"
    assert (state.away_team, state.home_team) == ("San Francisco 49ers", "Seattle Seahawks")
    assert (state.away_score, state.home_score) == (32, 29)
    assert state.quarter == 4
    assert state.clock_seconds == 110
    assert state.clock_display == "1:50"
    assert state.down == 1
    assert state.distance == 10
    assert state.yard_line_raw is not None and str(state.yard_line_raw) == "15"
    # Yard line is NOT normalized without a side marker -- no guessing.
    assert state.yard_line_100 is None
    assert state.timeouts_home == 2
    assert state.timeouts_away == 2


def test_football_overtime_flag():
    event = load("nfl_live_event.json")
    state = parse_espn_football_event(event, sport="NFL", retrieved_at=NOW)
    assert not state.is_overtime()
    ot = FootballGameState(**{**state.__dict__, "quarter": 5})
    assert ot.is_overtime()


def test_parse_cfb_final_event():
    event = load("cfb_event.json")
    state = parse_espn_football_event(event, sport="CFB", retrieved_at=NOW)
    assert state.status == "FINAL"
    assert (state.away_score, state.home_score) == (10, 24)


def test_football_missing_competitors_fails_closed():
    with pytest.raises(LiveStateError):
        parse_espn_football_event({"id": "x", "competitions": []},
                                  sport="NFL", retrieved_at=NOW)


def test_football_bad_sport_fails_closed():
    with pytest.raises(LiveStateError):
        parse_espn_football_event(load("nfl_live_event.json"), sport="NBA",
                                  retrieved_at=NOW)


def test_naive_datetime_rejected():
    feed = load("mlb_feed_final.json")
    with pytest.raises(LiveStateError):
        parse_mlb_live_feed(feed, retrieved_at=datetime(2026, 10, 11, 23, 40))
