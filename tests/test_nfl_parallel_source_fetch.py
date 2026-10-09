"""Offline PIT/source completeness tests for the unified NFL command."""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_nfl_unified_lines_card.py"


def _module():
    spec = importlib.util.spec_from_file_location("nfl_parallel_source_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, monkeypatch, module, seasons=(2025, 2026)):
    ticket = tmp_path / "ticket.json"
    history = tmp_path / "history.json"
    output = tmp_path / "out.json"
    ticket.write_text(json.dumps({
        "observed_at": "2026-10-08T15:00:00-05:00",
        "games": [{"markets": [{"player": "Example Player"}]}],
    }))
    history.write_text("[]")
    monkeypatch.setattr(module, "discover_nfl_auto_games", lambda **kwargs: {
        "games": [{"season": season} for season in seasons],
        "schedule_source_sha256": "synthetic-only",
    })
    captured = {}
    def build(*args, **kwargs):
        captured.update(kwargs)
        return {"games": [], "rows": [], "selected_rows": []}
    monkeypatch.setattr(module, "build_unified_phone_card", build)
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT), "--input", str(ticket), "--history", str(history),
        "--output", str(output),
    ])
    assert module.main() == 0
    return json.loads(output.read_text()), captured


def test_partial_depth_family_never_reaches_card(tmp_path, monkeypatch):
    module = _module()
    def depth(*, season):
        if season == 2026:
            raise module.NFLContextError("depth:2026")
        return ([{"season": season}], "", "")
    monkeypatch.setattr(module, "fetch_nflverse_depth_charts", depth)
    monkeypatch.setattr(module, "fetch_nflverse_player_stats", lambda **kw: ([], []))
    monkeypatch.setattr(module, "fetch_nflverse_injuries", lambda **kw: ([], "", ""))
    result, captured = _run(tmp_path, monkeypatch, module)
    assert captured["depth_rows"] == []
    assert result["source_status"]["depth"] == "MISSING:depth:2026"
    assert result["source_status"]["player_stats"] == "AVAILABLE"


def test_injury_partial_failure_does_not_mark_ready(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_nflverse_depth_charts", lambda **kw: ([], "", ""))
    monkeypatch.setattr(module, "fetch_nflverse_player_stats", lambda **kw: ([], []))
    def injuries(*, season):
        if season == 2026:
            raise RuntimeError("provider unavailable")
        return ([{"season": season}], "", "")
    monkeypatch.setattr(module, "fetch_nflverse_injuries", injuries)
    result, captured = _run(tmp_path, monkeypatch, module)
    assert captured["injury_rows"] == []
    assert captured["injury_source_ready"] is False
    assert result["source_status"]["injuries"] == "SOURCE_FAILED:INJURIES:RuntimeError"


def test_seasons_deterministic_and_stats_deduplicated(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_nflverse_depth_charts", lambda *, season: ([{"season": season}], "", ""))
    monkeypatch.setattr(module, "fetch_nflverse_injuries", lambda *, season: ([{"season": season}], "", ""))
    stat_calls = []
    def stats(*, seasons):
        stat_calls.append(seasons)
        return ([], [])
    monkeypatch.setattr(module, "fetch_nflverse_player_stats", stats)
    result, captured = _run(tmp_path, monkeypatch, module, seasons=(2026, 2025, 2026))
    assert [r["season"] for r in captured["depth_rows"]] == [2025, 2026]
    assert [r["season"] for r in captured["injury_rows"]] == [2025, 2026]
    assert stat_calls == [[2024, 2025, 2026]]
    assert result["source_status"]["injuries"] == "AVAILABLE"


def test_source_families_can_overlap_without_cross_family_data(tmp_path, monkeypatch):
    module = _module()
    barrier = threading.Barrier(3, timeout=5)
    def depth(*, season):
        barrier.wait()
        return ([{"source": "depth", "season": season}], "", "")
    def stats(*, seasons):
        barrier.wait()
        return ([{"source": "stats"}], [])
    def injuries(*, season):
        barrier.wait()
        return ([{"source": "injury", "season": season}], "", "")
    monkeypatch.setattr(module, "fetch_nflverse_depth_charts", depth)
    monkeypatch.setattr(module, "fetch_nflverse_player_stats", stats)
    monkeypatch.setattr(module, "fetch_nflverse_injuries", injuries)
    result, captured = _run(tmp_path, monkeypatch, module, seasons=(2026,))
    assert result["source_status"]["depth"] == "AVAILABLE"
    assert result["source_status"]["player_stats"] == "AVAILABLE"
    assert result["source_status"]["injuries"] == "AVAILABLE"
    assert captured["depth_rows"][0]["source"] == "depth"
    assert captured["player_rows"][0]["source"] == "stats"
    assert captured["injury_rows"][0]["source"] == "injury"
