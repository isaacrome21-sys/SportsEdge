"""The remote SHA check must send an explicit User-Agent (GitHub API requirement)."""
import io
import json
import urllib.request

from scripts import completion_gap_ledger as L


def test_resolver_sends_user_agent(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return io.BytesIO(json.dumps({"status": "identical"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert L._github_resolver("grok/x", "a" * 40) == "head"
    assert seen["ua"] and seen["ua"].startswith("sportsedge-completion-gap-ledger")


def _limited():
    import urllib.error
    from email.message import Message
    h = Message(); h["x-ratelimit-remaining"] = "0"
    return urllib.error.HTTPError("u", 403, "rate limited", h, io.BytesIO(b"{}"))


def test_rate_limited_403_is_retried_then_succeeds(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise _limited()
        return io.BytesIO(json.dumps({"status": "identical"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert L._github_resolver("grok/x", "a" * 40, sleep=lambda s: None) == "head"
    assert len(calls) == 3


def test_persistent_rate_limit_fails_closed(monkeypatch):
    import pytest

    def fake_urlopen(req, timeout=None):
        raise _limited()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(L.LedgerRefusal, match="REMOTE_CHECK_UNAVAILABLE:403"):
        L._github_resolver("grok/x", "a" * 40, sleep=lambda s: None)


def test_non_rate_limit_403_is_not_retried(monkeypatch):
    import urllib.error
    import pytest
    from email.message import Message
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError("u", 403, "forbidden", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(L.LedgerRefusal, match="REMOTE_CHECK_UNAVAILABLE:403"):
        L._github_resolver("grok/x", "a" * 40, sleep=lambda s: None)
    assert len(calls) == 1
