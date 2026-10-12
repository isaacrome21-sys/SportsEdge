"""Tests for sportsedge.cfbd_client. Fake key, stubbed transport.

No network. No real secrets. The fake key value must never appear in any
error message, log line, or exception repr.
"""

import io
import json
import urllib.error
import urllib.request

import pytest

from sportsedge.cfbd_client import (
    CFBDClient,
    CFBDBudgetExhausted,
    CFBDError,
    CFBDKeyMissing,
    CFBDNotWired,
    CFBDTierGated,
    KEY_ENV_VAR,
)

FAKE_KEY = "fake-key-for-tests-only"


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_urlopen(monkeypatch, handler):
    monkeypatch.setattr(urllib.request, "urlopen", handler)


def test_missing_key_fails_closed():
    with pytest.raises(CFBDKeyMissing) as excinfo:
        CFBDClient.from_env(env={})
    assert KEY_ENV_VAR in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)


def test_blank_key_fails_closed():
    with pytest.raises(CFBDKeyMissing):
        CFBDClient.from_env(env={KEY_ENV_VAR: "   "})


def test_key_from_env_only():
    client = CFBDClient.from_env(env={KEY_ENV_VAR: FAKE_KEY})
    assert client.calls_made == 0


def test_sp_ratings_never_fires(monkeypatch):
    """SP+ raises before any HTTP request; budget is never burned probing it."""
    calls = []

    def boom(request, timeout=None):
        calls.append(request)
        raise AssertionError("no HTTP request should be made")

    _stub_urlopen(monkeypatch, boom)
    client = CFBDClient(api_key=FAKE_KEY)
    with pytest.raises(CFBDNotWired) as excinfo:
        client.sp_ratings(2025)
    assert "/ratings/sp" in str(excinfo.value)
    assert calls == []


def test_paid_tier_gated_set_blocks_request(monkeypatch):
    calls = []

    def boom(request, timeout=None):
        calls.append(request)
        raise AssertionError("no HTTP request should be made")

    _stub_urlopen(monkeypatch, boom)
    client = CFBDClient(api_key=FAKE_KEY)
    with pytest.raises(CFBDNotWired):
        client._request("/ratings/sp")
    assert calls == []


def test_403_maps_to_tier_gated_without_key_leak(monkeypatch):
    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden",
                                     {}, io.BytesIO(b"{}"))

    _stub_urlopen(monkeypatch, forbidden)
    client = CFBDClient(api_key=FAKE_KEY)
    with pytest.raises(CFBDTierGated) as excinfo:
        client.season_advanced(2025)
    message = str(excinfo.value)
    assert FAKE_KEY not in message
    assert "/stats/season/advanced" in message


def test_500_maps_to_generic_error_without_key_leak(monkeypatch):
    def broken(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error",
                                     {}, io.BytesIO(b"{}"))

    _stub_urlopen(monkeypatch, broken)
    client = CFBDClient(api_key=FAKE_KEY)
    with pytest.raises(CFBDError) as excinfo:
        client.game_advanced(2025, 7)
    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in repr(excinfo.value)


def test_key_sent_as_bearer_but_never_in_url(monkeypatch):
    seen = {}

    def capture(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return FakeResponse({"tier": "free", "limit": 1000, "remaining": 999})

    _stub_urlopen(monkeypatch, capture)
    client = CFBDClient(api_key=FAKE_KEY)
    info = client.get_info()
    assert info["remaining"] == 999
    assert FAKE_KEY not in seen["url"]
    assert seen["auth"] == "Bearer " + FAKE_KEY
    assert client.calls_made == 1


def test_garbage_time_always_excluded(monkeypatch):
    seen = {}

    def capture(request, timeout=None):
        seen["url"] = request.full_url
        return FakeResponse([])

    _stub_urlopen(monkeypatch, capture)
    client = CFBDClient(api_key=FAKE_KEY)
    client.season_advanced(2025)
    assert "excludeGarbageTime=true" in seen["url"]
    client.ppa_games(2025, 3)
    assert "excludeGarbageTime=true" in seen["url"]


def test_malformed_payload_fails_closed(monkeypatch):
    def bad_json(request, timeout=None):
        return FakeResponse({"not": "a list"})

    _stub_urlopen(monkeypatch, bad_json)
    client = CFBDClient(api_key=FAKE_KEY)
    with pytest.raises(CFBDError):
        client.season_advanced(2025)
