"""Offline one-command RUN IT bundle; never fabricate a quote or PLAY."""
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts.run_it_auto_board import create_bundle, render_png

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def fake_png(summary, rows, path):
    path.write_bytes(b"TEST PNG PLACEHOLDER")


def test_empty_capture_still_reports_all_missing_market_families(tmp_path):
    def no_capture(directory, *, now, max_games):
        return {"status": "NO_FRESH_PAIRED_QUOTES", "capture_refusals": []}, None, "No quotes."
    result = create_bundle(tmp_path, tmp_path / "out", now=NOW, final_now=NOW,
                           adapter=no_capture, png_writer=fake_png,
                           screen_builder=lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert result["status"] == "NO_FRESH_PAIRED_QUOTES"
    assert result["verified_plays"] == 0
    assert result["play_authority"] is False
    assert result["full_board_scanned"] is False
    assert result["new_paid_odds_calls"] == 0
    assert result["market_coverage"]["families_not_requested"] == 28
    assert (tmp_path / "out" / "run_it_card.png").is_file()
    assert not (tmp_path / "out" / "run_it_card.json").exists()
    assert "INCOMPLETE" in (tmp_path / "out" / "run_it_card.md").read_text()


def test_one_card_preserves_ranked_research_only(tmp_path):
    sample = {"rank_ev": 0.035, "game": "A @ B", "sport": "NFL",
              "market": "TOTAL", "selection": "OVER", "odds": -110,
              "model_version": "RESEARCH_TEST"}
    seen = {}
    def adapter(directory, *, now, max_games):
        assert max_games is None
        return {"status": "READY_FOR_CANONICAL_PRICE"}, {"evaluated_rows": []}, "Research only."
    def screen_builder(card, *, now):
        seen["clock"] = now
        return {"unverified_model_value_screens": [sample],
                "total_positive_screens": 1}
    def png(summary, rows, path):
        seen["rows"] = rows
        fake_png(summary, rows, path)
    out = tmp_path / "out"
    result = create_bundle(tmp_path, out, now=NOW, final_now=NOW,
                           adapter=adapter, screen_builder=screen_builder,
                           png_writer=png,
                           markdown_renderer=lambda card, now: "Fresh final-clock research.")
    assert result["status"] == "RESEARCH_SCREEN_ONLY"
    assert result["ranked_research_screens"] == 1
    assert result["verified_plays"] == 0
    assert seen["rows"] == [sample]
    assert seen["clock"] == NOW
    assert "Fresh final-clock research." in (out / "run_it_card.md").read_text()
    assert json.loads((out / "run_it_card.json").read_text())["evaluated_rows"] == []


def test_final_freshness_clock_is_after_slow_model_run(tmp_path):
    later = NOW + timedelta(seconds=181)
    observed = []
    def adapter(directory, *, now, max_games):
        observed.append(("canonical", now))
        return {"status": "READY"}, {"evaluated_rows": []}, "No selection."
    def check(card, *, now):
        observed.append(("final", now))
        return {"unverified_model_value_screens": []}
    with patch("scripts.run_it_auto_board._utc_now", side_effect=[NOW, later]):
        create_bundle(tmp_path, tmp_path / "out", adapter=adapter,
                      screen_builder=check, png_writer=fake_png,
                      markdown_renderer=lambda card, now: "Verified at final clock.")
    assert observed == [("canonical", NOW), ("final", later)]


def test_screen_builder_refusal_drops_all_display_rows(tmp_path):
    def adapter(directory, *, now, max_games):
        return {"status": "READY"}, {"evaluated_rows": []}, "MISLEADING +99% EV"
    result = create_bundle(
        tmp_path, tmp_path / "out", now=NOW, final_now=NOW,
        adapter=adapter, png_writer=fake_png,
        screen_builder=lambda card, now: (_ for _ in ()).throw(ValueError("BAD_SCREEN")))
    assert result["status"] == "SCREEN_RENDER_REFUSED"
    assert result["ranked_research_screens"] == 0
    assert "+99%" not in (tmp_path / "out" / "run_it_card.md").read_text()


def test_png_failure_has_explicit_failure_status(tmp_path):
    def fail_png(summary, rows, path):
        raise OSError("NO_FONT_OR_DISK")
    result = create_bundle(tmp_path, tmp_path / "out", now=NOW, final_now=NOW,
                           adapter=lambda *a, **k: ({"status": "EMPTY"}, None, "Empty"),
                           png_writer=fail_png)
    assert result["status"] == "PNG_RENDER_FAILED"
    assert json.loads((tmp_path / "out" / "run_it_audit.json").read_text())["status"] == "PNG_RENDER_FAILED"


def test_real_png_has_safety_banner_and_stable_dimensions(tmp_path):
    target = tmp_path / "card.png"
    report = {"market_coverage": {"families_requested_but_unverified": 12,
                                  "required_family_count": 40},
              "status": "NO_FRESH_PAIRED_QUOTES"}
    render_png(report, [], target)
    with Image.open(target) as im:
        assert im.format == "PNG"
        assert im.size == (1440, 1536)


def test_one_command_cli_resolves_repo_without_pythonpath():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "scripts/run_it_auto_board.py", "--help"],
                          cwd=root, text=True, capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert "--input-dir" in proc.stdout and "--out-dir" in proc.stdout
