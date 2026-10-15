"""Tests for the M49 Plate Appearance named gates (wiring queue 6).

DraftKings offers three per-batter first-plate-appearance forms
(1st PA Result multi-outcome, On Base Yes/No, Grouped Result
3-way). They are not among the 89 matrix markets and have no
engine; intake rows for them used to fall through the canonical
card to the generic NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback.
They now refuse at truthful named gates carried by
sportsedge.mlb_plate_appearance_gates (the mlb_total_hits pattern
-- the 89-market canonical_coverage table is the matrix contract
and is NOT extended):

* All three forms: PLATE_APPEARANCE_PBP_POOL_UNBUILT -- StatsAPI
  play-by-play carries the events but no canonical-path
  construction consumes them into a verified strictly-prior
  first-PA outcome pool.
* Every row's detail also names
  PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED -- the catalog evidence
  names the market forms, not DK's exact selection lists or the
  Grouped Result partition, so no settlement basis can be
  verified.

Label refinements ONLY: pricing stays refused on every path, no
probability or EV may appear, and no registry/deployment/validation
state changes.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)

POOL_GATE = "PLATE_APPEARANCE_PBP_POOL_UNBUILT"
GATES = {
    "PLATE_APPEARANCE_RESULT": POOL_GATE,
    "PLATE_APPEARANCE_ON_BASE": POOL_GATE,
    "PLATE_APPEARANCE_GROUPED_RESULT": POOL_GATE,
}
ALIASES = {
    "FIRST_PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "FIRST_PLATE_APPEARANCE_RESULT": "PLATE_APPEARANCE_RESULT",
    "PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "PLATE_APPEARANCE_1ST_PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "PA_ON_BASE": "PLATE_APPEARANCE_ON_BASE",
    "FIRST_PA_ON_BASE": "PLATE_APPEARANCE_ON_BASE",
    "PLATE_APPEARANCE_ON_BASE_YES_NO": "PLATE_APPEARANCE_ON_BASE",
    "PA_GROUPED_RESULT": "PLATE_APPEARANCE_GROUPED_RESULT",
    "FIRST_PA_GROUPED_RESULT": "PLATE_APPEARANCE_GROUPED_RESULT",
    "PLATE_APPEARANCE_GROUPED": "PLATE_APPEARANCE_GROUPED_RESULT",
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
def test_plate_appearance_refuses_at_its_named_gate(market, gate):
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(f"NO_ENGINE: {gate}")
    assert result["plate_appearance_gate"] == gate
    assert result["coverage_market"] == market
    # The second truthful blocker is named on the record too.
    assert "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED" in (
        result["blocker_detail"])
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


def test_bare_family_name_refuses_at_the_pool_gate():
    result = _run(_row("PLATE_APPEARANCE", side=None, selection=None))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["reason"].startswith(f"NO_ENGINE: {POOL_GATE}")
    assert result["coverage_market"] == "PLATE_APPEARANCE"
    for key in ("model_p", "model_probability", "ev", "expected_value"):
        assert key not in result


def test_bare_family_name_infers_form_from_the_row():
    result = _run(_row("PLATE_APPEARANCE", side="YES"))
    assert result["coverage_market"] == "PLATE_APPEARANCE_ON_BASE"
    result = _run(_row("PLATE_APPEARANCE", side="SINGLE"))
    assert result["coverage_market"] == "PLATE_APPEARANCE_RESULT"


def test_plate_appearance_markets_stay_outside_the_matrix_table():
    # canonical_coverage is the exact 89-market matrix contract; the
    # PA forms must NOT be added to it. The gates live in the PA
    # module instead.
    from sportsedge.canonical_coverage import resolve_market
    from sportsedge.mlb_plate_appearance_gates import (
        PLATE_APPEARANCE_GATES, canonical_plate_appearance_market)
    for market, (gate, _detail) in PLATE_APPEARANCE_GATES.items():
        assert resolve_market("MLB", market) is None, market
        assert canonical_plate_appearance_market(market) == market
        assert GATES[market] == gate


def test_unrelated_market_still_hits_the_generic_fallback():
    result = _run(_row("SOME_UNLISTED_MARKET"))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" in result["reason"]
