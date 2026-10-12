"""Regression tests for bounded MLB full-season schedule downloads.

All HTTP responses are synthetic. No network, no odds calls, no capture files.
"""
import json

import pytest

from sportsedge.backtest import outcomes


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, limit):
        self.read_sizes.append(limit)
        return self.payload[:limit]


def test_late_season_hydrated_schedule_over_old_8mb_limit(monkeypatch, tmp_path):
    """A 13 MB valid JSON response must be parsed in full, never truncated."""
    fixture = {"dates": [{"date": "2026-10-12", "games": []}],
               "padding": "x" * 13_094_000}
    payload = json.dumps(fixture).encode("utf-8")
    assert 13_000_000 < len(payload) < outcomes._PUBLIC_JSON_MAX_BYTES
    response = FakeResponse(payload)
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        assert timeout == 20
        return response

    monkeypatch.setattr(outcomes, "urlopen", fake_urlopen)
    dates = outcomes.fetch_mlb_schedule(
        "2026-01-01", "2026-10-12", cache_dir=tmp_path,
    )
    assert dates == fixture["dates"]
    assert len(urls) == 1
    assert "hydrate=linescore" in urls[0]
    assert "startDate=2026-01-01" in urls[0]
    assert "endDate=2026-10-12" in urls[0]
    assert response.read_sizes == [outcomes._PUBLIC_JSON_MAX_BYTES + 1]
    # Cache is still only written after the entire payload parses.
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_oversized_schedule_fails_closed_without_caching(monkeypatch, tmp_path):
    """An over-limit response must refuse rather than parse a clipped prefix."""
    monkeypatch.setattr(outcomes, "_PUBLIC_JSON_MAX_BYTES", 128)
    payload = json.dumps({"dates": [], "padding": "x" * 500}).encode("utf-8")
    response = FakeResponse(payload)
    monkeypatch.setattr(
        outcomes, "urlopen", lambda _req, timeout: response,
    )
    with pytest.raises(outcomes.OutcomeError, match="BACKTEST_SOURCE_UNAVAILABLE"):
        outcomes.fetch_mlb_schedule("2026-01-01", "2026-10-12", cache_dir=tmp_path)
    assert response.read_sizes == [129]
    assert list(tmp_path.glob("*.json")) == []


def test_invalid_response_remains_unavailable(monkeypatch):
    """Increasing a cap does not authorize malformed source responses."""
    response = FakeResponse(b'{"dates": [}')
    monkeypatch.setattr(
        outcomes, "urlopen", lambda _req, timeout: response,
    )
    with pytest.raises(outcomes.OutcomeError, match="BACKTEST_SOURCE_UNAVAILABLE"):
        outcomes.fetch_mlb_schedule("2026-01-01", "2026-10-12")
