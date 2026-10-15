"""Tests for the M32/M33 named-gate refinements (wiring queue 3-4).

PITCHER_RECORD_WIN and FIRST_HOME_RUN used to refuse with the shared
generic NO_ENGINE text "No engine for this market is reachable from
the canonical intake" -- which was never the real reason for either:
a probability construction exists in research code for both (the
win-credit candidate engine; the batting-order first-HR candidate).
Per the backtest matrix (M32/M33) and the wiring queue, the card now
states each family's truthful gate:

* M32: PITCHER_RECORD_WIN_OFFERING_UNVERIFIED -- no verified
  DraftKings offering rows on the enumerated board; behind it the
  engine is an unvalidated candidate by its own module statement.
* M33: FIRST_HOME_RUN_ABSENT_ON_ENUMERATED_BOARD -- the market was
  absent on the sampled board; behind it the market is multi-outcome
  (an N-way field) with no selection-set binding on the canonical
  path.

These are truthful-label changes ONLY: pricing stays refused on
every path, no probability or EV may appear, and no
registry/deployment/validation state changes.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)


def _row(market, **kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": market, "side": "YES", "line": None,
            "odds": 150, "player": "Some Player"}
    base.update(kw)
    return base


def _run(row):
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [row], "sport": "MLB"}, now=NOW,
                    auto_context=False)
    return card["evaluated_rows"][0]


def test_record_win_refuses_at_the_named_offering_gate():
    result = _run(_row("PITCHER_RECORD_WIN"))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(
        "NO_ENGINE: PITCHER_RECORD_WIN_OFFERING_UNVERIFIED")
    assert "PITCHER_RECORD_WIN_ENGINE_CANDIDATE_UNVALIDATED" in result["reason"]
    # The generic text is gone for this family.
    assert "No engine for this market is reachable" not in result["reason"]
    # Label only: no priced keys may appear.
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


def test_first_home_run_refuses_at_the_named_board_gate():
    result = _run(_row("FIRST_HOME_RUN"))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(
        "NO_ENGINE: FIRST_HOME_RUN_ABSENT_ON_ENUMERATED_BOARD")
    assert "FIRST_HOME_RUN_MULTI_OUTCOME_SELECTION_SET_UNBOUND" in result["reason"]
    assert "No engine for this market is reachable" not in result["reason"]
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


def test_coverage_rows_carry_the_named_gates():
    from sportsedge.canonical_coverage import resolve_market
    win = resolve_market("MLB", "PITCHER_RECORD_WIN")
    assert win["blocker"] == "NO_ENGINE"
    assert "PITCHER_RECORD_WIN_OFFERING_UNVERIFIED" in win["detail"]
    assert "credit-state candidate" in win["engine"]
    hr = resolve_market("MLB", "FIRST_HOME_RUN")
    assert hr["blocker"] == "NO_ENGINE"
    assert "FIRST_HOME_RUN_ABSENT_ON_ENUMERATED_BOARD" in hr["detail"]
    assert "MULTI-OUTCOME" in hr["detail"]
    assert "lineup-order candidate" in hr["engine"]
