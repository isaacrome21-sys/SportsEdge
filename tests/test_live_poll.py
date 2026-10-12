"""Tests for sportsedge.live_poll: budgets, cadence, fail-closed fetching.

Network-free: the getter is injected; the 429 path is simulated.
"""
import time
from datetime import datetime, timezone

import pytest

from sportsedge.live_poll import (
    LIVE_MAX_REQUESTS_PER_MINUTE,
    LIVE_POLL_CADENCE_SECONDS,
    LiveFetchError,
    LivePoller,
    LiveRateLimited,
    PollBudget,
)


def test_poll_cadence_is_30s():
    assert LIVE_POLL_CADENCE_SECONDS == 30


def test_budget_cap_is_conservative():
    assert LIVE_MAX_REQUESTS_PER_MINUTE <= 60


def test_budget_allows_burst_under_cap():
    budget = PollBudget(max_per_minute=5, spacing_seconds=0)
    for _ in range(5):
        budget.acquire()
    assert budget.used_in_window == 5


def test_poll_due_respects_cadence():
    poller = LivePoller(getter=lambda url: {})
    assert poller.poll_due("game:1") is True
    assert poller.poll_due("game:1") is False
    assert poller.poll_due("game:2") is True


def test_fetch_wraps_getter_errors():
    def boom(url):
        raise ConnectionError("down")

    poller = LivePoller(getter=boom,
                        budget=PollBudget(max_per_minute=100, spacing_seconds=0))
    with pytest.raises(LiveFetchError):
        poller._fetch("https://example.com/x")


def test_rate_limited_propagates_without_retry():
    calls = []

    def limited(url):
        calls.append(url)
        raise LiveRateLimited("429 from https://example.com/x")

    poller = LivePoller(getter=limited,
                        budget=PollBudget(max_per_minute=100, spacing_seconds=0))
    with pytest.raises(LiveRateLimited):
        poller.fetch_mlb_state(123)
    assert len(calls) == 1  # no retry loop


def test_fetch_mlb_state_receipt_provenance():
    import json
    from pathlib import Path
    feed = json.loads(
        (Path(__file__).parent / "fixtures" / "live" / "mlb_feed_final.json")
        .read_text(encoding="utf-8"))

    seen = []

    def getter(url):
        seen.append(url)
        assert "game/849831/feed/live" in url
        return feed

    now = datetime(2026, 10, 11, 23, 40, tzinfo=timezone.utc)
    poller = LivePoller(getter=getter,
                        budget=PollBudget(max_per_minute=100, spacing_seconds=0),
                        now=lambda: now)
    state, receipt = poller.fetch_mlb_state(849831)
    assert state.game_pk == 849831
    assert receipt["status"] == "FETCHED"
    assert "retrieved_at_utc" in receipt
    assert receipt["game_status"] == "FINAL"


def test_fetch_football_state_by_event_id():
    import json
    from pathlib import Path
    event = json.loads(
        (Path(__file__).parent / "fixtures" / "live" / "nfl_live_event.json")
        .read_text(encoding="utf-8"))

    def getter(url):
        assert "football/nfl/scoreboard" in url
        return {"events": [event]}

    now = datetime(2026, 10, 11, 23, 40, tzinfo=timezone.utc)
    poller = LivePoller(getter=getter,
                        budget=PollBudget(max_per_minute=100, spacing_seconds=0),
                        now=lambda: now)
    state, receipt = poller.fetch_football_state("NFL", event_id="401872992")
    assert state.status == "LIVE"
    assert receipt["game_status"] == "LIVE"


def test_fetch_football_event_not_found():
    def getter(url):
        return {"events": []}

    poller = LivePoller(getter=getter,
                        budget=PollBudget(max_per_minute=100, spacing_seconds=0))
    from sportsedge.live_state import LiveStateError
    with pytest.raises(LiveStateError):
        poller.fetch_football_state("NFL", event_id="nope")


def test_budget_spacing_keeps_bursts_down():
    budget = PollBudget(max_per_minute=100, spacing_seconds=0.05)
    start = time.monotonic()
    budget.acquire()
    budget.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04
