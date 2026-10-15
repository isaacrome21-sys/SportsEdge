"""Offline synthetic acquisition tests: no live network calls."""
import json
from pathlib import Path

import pytest

from sportsedge import mlb_historical_feed_fetcher as fetcher


def _stub(url):
    if "/schedule?" in url:
        payload = {"dates": [{"games": [
            {"gamePk": 100, "status": {"abstractGameState": "Final"}},
            {"gamePk": 101, "status": {"abstractGameState": "Final"}},
        ]}]}
    else:
        pk = int(url.split("/game/")[1].split("/")[0])
        payload = {"gamePk": pk, "gameData": {
            "game": {"pk": pk}, "status": {"abstractGameState": "Final"},
            "datetime": {"dateTime": "2024-04-01T18:00:00Z"}}}
    raw = json.dumps(payload).encode()
    return raw, payload


def test_research_acquisition_creates_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_json", _stub)
    output = tmp_path / "historical"
    result = fetcher.acquire_historical_date("2024-04-01", output)
    assert result["games"] == 2
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["no_pit_market_evidence"] is True
    assert manifest["feed_paths"] == ["game-100.json", "game-101.json"]
    assert (output / "schedule.json").exists()


def test_failed_feed_does_not_publish_partial_output(tmp_path, monkeypatch):
    def broken(url):
        if "/game/101/" in url:
            raise OSError("network failure")
        return _stub(url)
    monkeypatch.setattr(fetcher, "_fetch_json", broken)
    output = tmp_path / "historical"
    with pytest.raises(OSError, match="network failure"):
        fetcher.acquire_historical_date("2024-04-01", output)
    assert not output.exists()


def test_duplicate_schedule_game_refused(tmp_path, monkeypatch):
    def duplicate(url):
        raw, data = _stub(url)
        if "/schedule?" in url:
            data["dates"][0]["games"][1]["gamePk"] = 100
        return raw, data
    monkeypatch.setattr(fetcher, "_fetch_json", duplicate)
    with pytest.raises(ValueError, match="DUPLICATE_SCHEDULE_GAME"):
        fetcher.acquire_historical_date("2024-04-01", tmp_path / "out")


def test_future_date_refused_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_json", lambda _: pytest.fail("network called"))
    with pytest.raises(ValueError, match="DATE_NOT_HISTORICAL"):
        fetcher.acquire_historical_date("2099-01-01", tmp_path / "out")


def test_existing_output_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_json", lambda _: pytest.fail("network called"))
    with pytest.raises(FileExistsError, match="OUTPUT_DIRECTORY_EXISTS"):
        fetcher.acquire_historical_date("2024-04-01", tmp_path)


def test_non_final_feed_refused_without_output(tmp_path, monkeypatch):
    def bad(url):
        raw, data = _stub(url)
        if "/game/101/" in url:
            data["gameData"]["status"]["abstractGameState"] = "Live"
        return raw, data
    monkeypatch.setattr(fetcher, "_fetch_json", bad)
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="NON_FINAL_FEED_GAME"):
        fetcher.acquire_historical_date("2024-04-01", output)
    assert not output.exists()


def test_mismatched_embedded_game_id_refused(tmp_path, monkeypatch):
    def bad(url):
        raw, data = _stub(url)
        if "/game/101/" in url:
            data["gameData"]["game"]["pk"] = 999
        return raw, data
    monkeypatch.setattr(fetcher, "_fetch_json", bad)
    with pytest.raises(ValueError, match="FEED_GAME_ID_MISMATCH"):
        fetcher.acquire_historical_date("2024-04-01", tmp_path / "out")


def test_naive_start_refused(tmp_path, monkeypatch):
    def bad(url):
        raw, data = _stub(url)
        if "/game/101/" in url:
            data["gameData"]["datetime"]["dateTime"] = "2024-04-01T18:00:00"
        return raw, data
    monkeypatch.setattr(fetcher, "_fetch_json", bad)
    with pytest.raises(ValueError, match="FUTURE_OR_NAIVE_FEED_START"):
        fetcher.acquire_historical_date("2024-04-01", tmp_path / "out")
