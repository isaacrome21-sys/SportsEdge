"""Tests for the M21 1st-inning deep-set named gates (wiring queue 5).

The deep-set sub-families (3-way, run line, odd/even, K thrown,
batters-to-plate) are not among the 89 matrix markets and are not
in the phone first-inning lane's market set; intake rows for them
used to fall through the canonical card to the generic
NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback. They now refuse at
truthful named gates carried by
sportsedge.mlb_first_inning_deep_set (the mlb_total_hits pattern --
the 89-market canonical_coverage table is the matrix contract and
is NOT extended):

* FIRST_INNING_3_WAY / _RUN_LINE / _ODD_EVEN:
  FIRST_INNING_COUNT_DISTRIBUTION_UNBUILT -- the canonical
  first-inning engine is binary (score/no-score per team); the
  Poisson count sibling was measured far worse at the binary
  itself, so no count joint is adopted without its own evaluation.
* FIRST_INNING_K: FIRST_INNING_PITCHER_K_PBP_POOL_UNBUILT.
* FIRST_INNING_BATTERS_TO_PLATE:
  FIRST_INNING_BATTERS_TO_PLATE_PBP_POOL_UNBUILT.

Team HR Y/N and pitches already refuse by name inside the phone
first-inning lane; those rows are pinned here too.

Label refinements ONLY: pricing stays refused on every path, no
probability or EV may appear, and no registry/deployment/validation
state changes.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)

COUNT_GATE = "FIRST_INNING_COUNT_DISTRIBUTION_UNBUILT"
GATES = {
    "FIRST_INNING_3_WAY": COUNT_GATE,
    "FIRST_INNING_RUN_LINE": COUNT_GATE,
    "FIRST_INNING_ODD_EVEN": COUNT_GATE,
    "FIRST_INNING_K": "FIRST_INNING_PITCHER_K_PBP_POOL_UNBUILT",
    "FIRST_INNING_BATTERS_TO_PLATE":
        "FIRST_INNING_BATTERS_TO_PLATE_PBP_POOL_UNBUILT",
}
ALIASES = {
    "FIRST_INNING_3WAY": "FIRST_INNING_3_WAY",
    "FIRST_INNING_MONEYLINE_3_WAY": "FIRST_INNING_3_WAY",
    "FIRST_INNING_ODD_OR_EVEN": "FIRST_INNING_ODD_EVEN",
    "FIRST_INNING_STRIKEOUTS": "FIRST_INNING_K",
    "FIRST_INNING_BATTERS_FACED": "FIRST_INNING_BATTERS_TO_PLATE",
}
PHONE_LANE_GATES = {
    "FIRST_INNING_HR": "FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE",
    "FIRST_INNING_PITCHES":
        "FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY",
}


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


@pytest.mark.parametrize("market,gate", sorted(GATES.items()))
def test_deep_set_refuses_at_its_named_gate(market, gate):
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(f"NO_ENGINE: {gate}")
    assert result["deep_set_gate"] == gate
    assert result["coverage_market"] == market
    # The generic fallback text is gone for these families.
    assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


@pytest.mark.parametrize("alias,canonical", sorted(ALIASES.items()))
def test_aliases_resolve_to_the_canonical_gate(alias, canonical):
    result = _run(_row(alias))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["reason"].startswith(f"NO_ENGINE: {GATES[canonical]}")
    assert result["coverage_market"] == canonical


@pytest.mark.parametrize("market,gate", sorted(PHONE_LANE_GATES.items()))
def test_phone_lane_markets_still_refuse_by_name(market, gate):
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert gate in result["reason"]
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


def test_deep_set_markets_stay_outside_the_matrix_table():
    # canonical_coverage is the exact 89-market matrix contract; the
    # deep set must NOT be added to it (test_canonical_run_it pins
    # the equality). The gates live in the deep-set module instead.
    from sportsedge.canonical_coverage import resolve_market
    from sportsedge.mlb_first_inning_deep_set import (
        FIRST_INNING_DEEP_SET_GATES, canonical_deep_set_market)
    for market, (gate, _detail) in FIRST_INNING_DEEP_SET_GATES.items():
        assert resolve_market("MLB", market) is None, market
        assert canonical_deep_set_market(market) == market
        assert GATES[market] == gate


def test_priced_first_inning_binary_unaffected():
    from sportsedge.canonical_coverage import resolve_market
    for market in ("NRFI", "YRFI"):
        entry = resolve_market("MLB", market)
        assert entry["state"] == "PRICED_PATH", market
