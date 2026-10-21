"""Regression for stale positive and negative NBA local-store cache.

The source may be created or advanced between two prospective board runs.
Re-reading a directory does not grant eligibility; existing ten-prior and PIT
guards still decide all player markets.
"""
from sportsedge import nba_phone_prop_pricing as pricing


def test_empty_directory_does_not_poison_later_load(monkeypatch, tmp_path):
    path = str(tmp_path / "nba_new")
    responses = [(None, pricing.STORE_UNAVAILABLE),
                 (object(), {"status": "NBA_PROP_STORE_LOADED"})]
    calls = []
    def reader(key):
        calls.append(key)
        return responses.pop(0)
    monkeypatch.setattr(pricing, "_load_store_uncached", reader)
    first, reason = pricing.load_store_from_dir(path)
    assert first is None and reason == pricing.STORE_UNAVAILABLE
    second, receipt = pricing.load_store_from_dir(path)
    assert second is not None
    assert receipt["status"] == "NBA_PROP_STORE_LOADED"
    assert calls == [path, path]


def test_updated_directory_does_not_reuse_stale_success(monkeypatch, tmp_path):
    path = str(tmp_path / "nba_old")
    versions = [(object(), {"status": "NBA_PROP_STORE_LOADED", "version": 1}),
                (object(), {"status": "NBA_PROP_STORE_LOADED", "version": 2})]
    calls = []
    def reader(key):
        calls.append(key)
        return versions.pop(0)
    monkeypatch.setattr(pricing, "_load_store_uncached", reader)
    one, receipt_one = pricing.load_store_from_dir(path)
    two, receipt_two = pricing.load_store_from_dir(path)
    assert one is not two
    assert receipt_one["version"] == 1
    assert receipt_two["version"] == 2
    assert len(calls) == 2


def test_no_directory_remains_fail_closed(monkeypatch):
    def unexpected(_):
        raise AssertionError("missing dir must not read")
    monkeypatch.setattr(pricing, "_load_store_uncached", unexpected)
    assert pricing.load_store_from_dir(None) == (None, pricing.STORE_UNAVAILABLE)
