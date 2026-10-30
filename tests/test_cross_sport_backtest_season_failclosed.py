"""Regression: invalid season must not crash whole cross-sport backtest report."""

from __future__ import annotations

import json
import sys

import pytest

from scripts import run_cross_sport_market_backtest as harness


def _row(season):
    return {
        "sport": "NFL", "market": "SPREAD", "season": season,
        "benchmark_p": 0.51, "outcome": 1,
        "selected": True, "offered_decimal": 1.91,
    }


@pytest.mark.parametrize("bad_season", [
    None, "unknown", "2025.0", 2025.5, True, [], {}, 0, -1,
])
def test_invalid_season_blocks_uncertainty_without_bootstrap(bad_season, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid season must not enter bootstrap")
    monkeypatch.setattr(harness, "paired_market_bootstrap", forbidden)
    monkeypatch.setattr(harness, "selected_betting_bootstrap", forbidden)
    paired = harness._safe_pair([_row(bad_season)], reps=50, seed=1)
    betting = harness._safe_betting([_row(bad_season)], reps=50, seed=1)
    assert paired == {
        "status": "UNAVAILABLE", "reason": "PAIRED_BENCHMARK_INVALID_SEASON"
    }
    assert betting == {
        "status": "UNAVAILABLE", "reason": "BETTING_UNCERTAINTY_INVALID_SEASON"
    }


def test_valid_two_seasons_still_enter_original_estimators(monkeypatch):
    rows = [_row("2025"), _row(2026)]
    monkeypatch.setattr(
        harness, "paired_market_bootstrap",
        lambda records, *, reps, seed: {"paired_called": len(records)},
    )
    monkeypatch.setattr(
        harness, "selected_betting_bootstrap",
        lambda records, *, reps, seed: {"betting_called": len(records)},
    )
    assert harness._safe_pair(rows, reps=50, seed=1) == {
        "status": "AVAILABLE", "paired_called": 2
    }
    assert harness._safe_betting(rows, reps=50, seed=1) == {
        "status": "AVAILABLE", "betting_called": 2
    }


def test_empty_or_single_season_preserves_existing_block_reasons():
    for rows in ([], [_row(2026)]):
        assert harness._safe_pair(rows, reps=50, seed=1)["reason"] == (
            "PAIRED_BENCHMARK_REQUIRES_MULTIPLE_SEASONS"
        )
        assert harness._safe_betting(rows, reps=50, seed=1)["reason"] == (
            "BETTING_UNCERTAINTY_REQUIRES_MULTIPLE_SEASONS"
        )


def test_report_survives_invalid_market_season(tmp_path, monkeypatch):
    rows = [_row(None), {**_row(2025), "sport": "MLB", "market": "MONEYLINE"}]
    input_path = tmp_path / "historical.jsonl"
    output_path = tmp_path / "audit.json"
    input_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(harness, "summarize_binary_market",
                        lambda records: {"test_summary_rows": len(records)})
    monkeypatch.setattr(sys, "argv", ["backtest", str(input_path),
                                     "--output", str(output_path)])
    assert harness.main() == 0
    audit = json.loads(output_path.read_text())
    assert audit["row_count"] == 2
    assert audit["market_count"] == 2
    assert audit["production_eligibility_changed"] is False
    by_sport = {entry["sport"]: entry for entry in audit["markets"]}
    assert by_sport["NFL"]["paired_benchmark_uncertainty"]["reason"] == (
        "PAIRED_BENCHMARK_INVALID_SEASON"
    )
    assert by_sport["NFL"]["selected_betting_uncertainty"]["reason"] == (
        "BETTING_UNCERTAINTY_INVALID_SEASON"
    )
    assert by_sport["MLB"]["status"] == "EVALUATED"
    assert by_sport["MLB"]["paired_benchmark_uncertainty"]["reason"] == (
        "PAIRED_BENCHMARK_REQUIRES_MULTIPLE_SEASONS"
    )
