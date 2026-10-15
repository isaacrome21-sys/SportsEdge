"""Synthetic manifest converter CLI tests."""
import hashlib
import json

import pytest

from sportsedge.mlb_statsapi_feed_cli import main


def _prepare(tmp_path):
    feed = {
        "gameData": {"game": {"pk": 12}, "status": {"abstractGameState": "Final"},
                     "datetime": {"dateTime": "2026-08-01T18:00:00Z"}},
        "liveData": {"linescore": {
            "innings": [{"num": i, "away": {"runs": 0}, "home": {"runs": 0}}
                        for i in range(1, 10)],
            "teams": {"away": {"runs": 0}, "home": {"runs": 0}},
        }},
    }
    source = tmp_path / "game.json"
    source.write_text(json.dumps(feed))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "MLB_FINAL_FEED_MANIFEST_V1",
        "source_url": "https://statsapi.mlb.com/api/v1.1/game/12/feed/live",
        "observed_at": "2026-10-01T00:00:00Z",
        "feed_paths": ["game.json"],
    }))
    return manifest, source


def test_cli_writes_hashed_evidence(tmp_path):
    manifest, source = _prepare(tmp_path)
    output = tmp_path / "export.json"
    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["games"][0]["game_id"] == "12"
    assert result["source_files"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_refuses_output_overwrite(tmp_path):
    manifest, _ = _prepare(tmp_path)
    with pytest.raises(FileExistsError, match="OUTPUT_ALREADY_EXISTS"):
        main(["--manifest", str(manifest), "--output", str(manifest)])


def test_refuses_path_traversal(tmp_path):
    manifest, _ = _prepare(tmp_path)
    data = json.loads(manifest.read_text())
    data["feed_paths"] = ["../other.json"]
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="UNSAFE_FEED_PATH"):
        main(["--manifest", str(manifest), "--output", str(tmp_path / "out.json")])


def test_refuses_duplicate_path(tmp_path):
    manifest, _ = _prepare(tmp_path)
    data = json.loads(manifest.read_text())
    data["feed_paths"] = ["game.json", "game.json"]
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="DUPLICATE_FEED_PATH"):
        main(["--manifest", str(manifest), "--output", str(tmp_path / "out.json")])
