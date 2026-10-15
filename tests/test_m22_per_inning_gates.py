"""Tests for the M22 per-inning 2nd-9th named gates (wiring queue 7).

DraftKings offers per-inning markets for innings 2-9 (Runs O/U,
Run Line, (3 Way) inning winner) and Result After Nth Inning
(3 Way, innings 2-8). They are not among the 89 matrix markets and
have no engine; intake rows for them used to fall through the
canonical card to the generic NO_VERIFIED_MODEL_FOR_THIS_MARKET
fallback. They now refuse at truthful named gates carried by
sportsedge.mlb_per_inning_gates (the mlb_total_hits pattern -- the
89-market canonical_coverage table is the matrix contract and is
NOT extended):

* INNING_<n>_RUNS / _RUN_LINE / _3_WAY (n=2..9):
  PER_INNING_DISTRIBUTION_UNBUILT -- the canonical period
  constructions are cumulative (first 3/5/7, full game); no
  per-inning joint exists and a cumulative joint cannot be
  differenced into honest per-inning mass.
* RESULT_AFTER_INNING_<n> (n=2..8):
  RESULT_AFTER_INNING_READOUT_UNBUILT -- no bound readout of the
  3-way result-after form exists for any N.

Label refinements ONLY: pricing stays refused on every path, no
probability or EV may appear, and no registry/deployment/validation
state changes. Inning 1 names are NOT claimed here (the first-
inning lanes own them).
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)

PER_INNING_GATE = "PER_INNING_DISTRIBUTION_UNBUILT"
RESULT_AFTER_GATE = "RESULT_AFTER_INNING_READOUT_UNBUILT"


def _row(market, **kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": market, "side": "HOME", "line": None,
            "odds": 150}
    base.update(kw)
    return base


def _run(row):
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [row], "sport": "MLB"}, now=NOW,
                    auto_context=False)
    return card["evaluated_rows"][0]


@pytest.mark.parametrize("n", range(2, 10))
@pytest.mark.parametrize("form", ["RUNS", "RUN_LINE", "3_WAY"])
def test_per_inning_forms_refuse_at_the_named_gate(n, form):
    market = f"INNING_{n}_{form}"
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(f"NO_ENGINE: {PER_INNING_GATE}")
    assert result["per_inning_gate"] == PER_INNING_GATE
    assert result["coverage_market"] == market
    assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


@pytest.mark.parametrize("n", range(2, 9))
def test_result_after_refuses_at_the_named_gate(n):
    market = f"RESULT_AFTER_INNING_{n}"
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["reason"].startswith(f"NO_ENGINE: {RESULT_AFTER_GATE}")
    assert result["per_inning_gate"] == RESULT_AFTER_GATE
    assert result["coverage_market"] == market
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


@pytest.mark.parametrize("alias,canonical", [
    ("5TH_INNING_RUNS", "INNING_5_RUNS"),
    ("INNING_5_TOTAL_RUNS", "INNING_5_RUNS"),
    ("INNING_7_MONEYLINE_3_WAY", "INNING_7_3_WAY"),
    ("INNING_7_WINNER", "INNING_7_3_WAY"),
    ("2ND_INNING_RUN_LINE", "INNING_2_RUN_LINE"),
    ("RESULT_AFTER_4_INNING", "RESULT_AFTER_INNING_4"),
    ("RESULT_AFTER_6TH_INNING", "RESULT_AFTER_INNING_6"),
])
def test_aliases_resolve_to_the_canonical_gate(alias, canonical):
    result = _run(_row(alias))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["coverage_market"] == canonical


def test_first_inning_names_are_not_claimed():
    from sportsedge.mlb_per_inning_gates import canonical_per_inning_market
    for name in ("INNING_1_RUNS", "INNING_1_RUN_LINE", "INNING_1_3_WAY",
                 "RESULT_AFTER_INNING_1", "RESULT_AFTER_INNING_9"):
        assert canonical_per_inning_market(name) is None, name


def test_per_inning_markets_stay_outside_the_matrix_table():
    from sportsedge.canonical_coverage import resolve_market
    from sportsedge.mlb_per_inning_gates import (
        PER_INNING_GATES, canonical_per_inning_market)
    assert len(PER_INNING_GATES) == 31
    for market, (gate, _detail) in PER_INNING_GATES.items():
        assert resolve_market("MLB", market) is None, market
        assert canonical_per_inning_market(market) == market
        assert gate in (PER_INNING_GATE, RESULT_AFTER_GATE)
