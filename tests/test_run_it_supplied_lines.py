"""The phone RUN IT command may evaluate research; it cannot mint PLAYs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.run_it_all import _supplied_line_run


ROOT = Path(__file__).resolve().parents[1]


def _lines(tmp_path: Path, rows: list[dict]) -> Path:
    target = tmp_path / "lines.json"
    target.write_text(json.dumps({"lines": rows}), encoding="utf-8")
    return target


def test_all_three_sports_accounted_without_manufacturing_verified_bets(
    tmp_path, monkeypatch,
):
    from artifacts import run_it_full

    seen = {}

    def fake_run(payload, *, auto_context, as_of):
        seen.update({"payload": payload, "auto_context": auto_context,
                     "as_of": as_of})
        return {"evaluated_rows": [
            {"status": "RESEARCH_POSITIVE_EV_UNVALIDATED", "estimate_p": .57,
             "play_eligible": True, "bet_status": "OFFICIAL_BET"},
            {"status": "NO_MODEL_OR_MARKET", "blocker": "NO_VALIDATION"},
            {"status": "NO_MODEL_OR_MARKET", "blocker": "NO_ENGINE"},
        ]}

    monkeypatch.setattr(run_it_full, "run_full", fake_run)
    card_path = tmp_path / "card.json"
    report = _supplied_line_run(
        _lines(tmp_path, [{"sport": "MLB"}, {"sport": "NBA"},
                          {"sport": "CFB"}]),
        requested_scope=("MLB", "NBA", "CFB"), no_fetch=True,
        as_of="2026-10-23T22:00:00Z", card_output=card_path,
    )
    assert seen["auto_context"] is False
    assert seen["as_of"] == "2026-10-23T22:00:00Z"
    assert report["scope"] == ["CFB", "MLB", "NBA"]
    assert {row["sport"] for row in report["results"]} == {
        "CFB", "MLB", "NBA"}
    mlb = next(row for row in report["results"] if row["sport"] == "MLB")
    assert mlb["research_candidates"] == 1
    assert mlb["official_bets"] == 0
    assert mlb["verified_plays"] == []
    assert report["verified_bets"] == 0
    assert report["verification_blocker"] == (
        "CANONICAL_RESEARCH_RUNNER_HAS_NO_PROMOTION_AUTHORITY")
    assert json.loads(card_path.read_text())["evaluated_rows"][0][
        "bet_status"] == "OFFICIAL_BET"  # Only the reporting boundary refuses it.


def test_explicit_scope_reports_missing_sports(tmp_path, monkeypatch):
    from artifacts import run_it_full

    monkeypatch.setattr(run_it_full, "run_full", lambda *a, **k: {
        "evaluated_rows": [{"status": "NO_MODEL_OR_MARKET"}]})
    report = _supplied_line_run(
        _lines(tmp_path, [{"sport": "MLB"}]),
        requested_scope=("MLB", "NBA", "CFB"), no_fetch=True,
        as_of=None, card_output=tmp_path / "card.json",
    )
    assert report["overall_status"] == "BLOCKED"
    assert {r["sport"]: r["blocker"] for r in report["results"]} == {
        "CFB": "NO_SUPPLIED_LINES_FOR_SPORT",
        "MLB": "NO_CANONICAL_MODEL_RESULT",
        "NBA": "NO_SUPPLIED_LINES_FOR_SPORT",
    }
    mlb = next(r for r in report["results"] if r["sport"] == "MLB")
    assert mlb["unpriced_reason_counts"] == {"NO_MODEL_OR_MARKET": 1}


@pytest.mark.parametrize("bad_probability", [True, -0.1, 1.01, float("nan"), "0.99"])
def test_invalid_probability_cannot_mark_sport_model_ready(
    tmp_path, monkeypatch, bad_probability,
):
    from artifacts import run_it_full

    monkeypatch.setattr(run_it_full, "run_full", lambda *a, **k: {
        "evaluated_rows": [{"status": "RESEARCH_EDGE",
                            "estimate_p": bad_probability,
                            "blocker": "MODEL_PROBABILITY_INVALID"}]})
    report = _supplied_line_run(
        _lines(tmp_path, [{"sport": "MLB"}]),
        requested_scope=None, no_fetch=True, as_of=None,
        card_output=tmp_path / "card.json")
    assert report["overall_status"] == "BLOCKED"
    assert report["results"][0]["model_rows"] == 0
    assert report["results"][0]["unpriced_reason_counts"] == {
        "MODEL_PROBABILITY_INVALID": 1}


@pytest.mark.parametrize("rows,scope,as_of,expected", [
    ([{"sport": "NHL"}], None, None, "RUN_IT_LINES_SPORT_UNSUPPORTED"),
    ([{"market": "ML"}], None, None, "RUN_IT_LINES_SPORT_UNSUPPORTED"),
    ([{"sport": "NBA"}], ("MLB",), None, "RUN_IT_LINES_OUTSIDE_SCOPE"),
    ([{"sport": "MLB"}], None, "2026-10-23T17:00:00", "RUN_IT_AS_OF_REQUIRES_TIMEZONE"),
    ([{"sport": "MLB"}], None, "garbage", "RUN_IT_AS_OF_INVALID"),
    (["not a row"], None, None, "RUN_IT_LINES_ROW_INVALID"),
])
def test_bad_inputs_fail_before_any_pricer(
    tmp_path, monkeypatch, rows, scope, as_of, expected,
):
    from artifacts import run_it_full

    monkeypatch.setattr(run_it_full, "run_full", lambda *a, **k:
                        pytest.fail("must not price invalid intake"))
    with pytest.raises(SystemExit, match=expected):
        _supplied_line_run(_lines(tmp_path, rows), requested_scope=scope,
                           no_fetch=True, as_of=as_of,
                           card_output=tmp_path / "card.json")
    assert not (tmp_path / "card.json").exists()


def test_dropped_canonical_rows_are_fatal(tmp_path, monkeypatch):
    from artifacts import run_it_full

    monkeypatch.setattr(run_it_full, "run_full", lambda *a, **k: {
        "evaluated_rows": []})
    with pytest.raises(SystemExit, match="RUN_IT_CANONICAL_EVALUATION_INCOMPLETE"):
        _supplied_line_run(_lines(tmp_path, [{"sport": "NBA"}]),
                           requested_scope=None, no_fetch=True, as_of=None,
                           card_output=tmp_path / "card.json")


def test_real_cli_three_sport_empty_board_reports_all_blocked(tmp_path):
    # A genuine CLI invocation routes through run_full and preserves explicit
    # empty-sport accounting; no network, no prices, no implied PLAYs.
    lines = _lines(tmp_path, [])
    output = tmp_path / "summary.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_it_all.py"),
         "--execute", "--scope", "MLB,NBA,CFB", "--lines", str(lines),
         "--no-fetch", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
    )
    assert proc.returncode == 2, proc.stderr[-3000:]
    result = json.loads(output.read_text())
    assert result["verified_bets"] == 0
    assert result["scope"] == ["CFB", "MLB", "NBA"]
    assert all(r["blocker"] == "NO_SUPPLIED_LINES_FOR_SPORT"
               for r in result["results"])
