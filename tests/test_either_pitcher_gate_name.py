"""Tests for the EITHER_PITCHER named-gate refinement (item 4).

The either-pitcher families (EITHER_PITCHER_HITS_ALLOWED / _BB / _ER)
used to refuse with the generic NO_ENGINE text "No engine for this
market is reachable from the canonical intake" — which was never the
real reason: an either-probability construction exists in the research
joint engine. Per the owner-approved decision package
(either_pitcher_design_20261014/DESIGN.md sections 3/5/7), the card now
states the truthful gate: EITHER_PITCHER_DEPENDENCE_UNMEASURED, with
EITHER_PITCHER_RUNG_LABEL_UNVERIFIED and
EITHER_PITCHER_PAIR_BINDING_INCOMPLETE named as also outstanding.

This is a truthful-label change ONLY: pricing stays refused on every
path, no probability or EV may appear, settlement stays fail-closed,
and no registry/deployment/validation state changes. Step 1 intake
plumbing from the design was NOT built here: the pair-resolution
machinery is not cleanly separable from the dependence gate, and the
gate rename must not risk any priced row.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
EITHER_MARKETS = ("EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB",
                  "EITHER_PITCHER_ER")
GATE = "EITHER_PITCHER_MARGINAL_TAIL_ERROR"  # renamed after M31 (was EITHER_PITCHER_DEPENDENCE_UNMEASURED)


def _row(market, **kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": market, "side": "OVER", "line": 5.5,
            "odds": -110, "player": "Either Pitcher"}
    base.update(kw)
    return base


def _run(row):
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [row], "sport": "MLB"}, now=NOW,
                    auto_context=False)
    return card["evaluated_rows"][0]


# ------------------------------------------------------------- the gate

@pytest.mark.parametrize("market", EITHER_MARKETS)
def test_either_families_refuse_at_the_named_dependence_gate(market):
    result = _run(_row(market))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["blocker"] == "NO_ENGINE"
    assert result["reason"].startswith(f"NO_ENGINE: {GATE}")
    # The generic text is gone for these families.
    assert "No engine for this market is reachable" not in result["reason"]


@pytest.mark.parametrize("market", EITHER_MARKETS)
def test_gate_reason_names_the_other_outstanding_items(market):
    # All three names lead the detail, so all three survive the card's
    # 400-character reason truncation and reach the reader.
    result = _run(_row(market))
    assert "EITHER_PITCHER_RUNG_LABEL_UNVERIFIED" in result["reason"]
    assert "EITHER_PITCHER_PAIR_BINDING_INCOMPLETE" in result["reason"]
    assert "OVERSTATES" in result["reason"]
    # The full reasoning (why independence is not assumed; what would
    # unblock pricing) lives in the untruncated coverage detail.
    from sportsedge.canonical_coverage import MARKET_RESOLUTIONS
    detail = MARKET_RESOLUTIONS[("MLB", market)]["detail"]
    assert "independence" in detail
    assert "M31 paired-starter audit" in detail
    assert "max/min" in detail


@pytest.mark.parametrize("market", EITHER_MARKETS)
def test_no_price_probability_or_ev_on_any_either_row(market):
    result = _run(_row(market))
    assert result.get("model_probability") is None
    assert result.get("estimate_p") is None
    assert result.get("ev") is None
    assert result.get("expected_value") is None


@pytest.mark.parametrize("market", EITHER_MARKETS)
def test_coverage_table_carries_the_gate(market):
    from sportsedge.canonical_coverage import MARKET_RESOLUTIONS
    entry = MARKET_RESOLUTIONS[("MLB", market)]
    assert entry["state"] == "BLOCKED"
    assert entry["blocker"] == "NO_ENGINE"
    assert GATE in entry["detail"]
    assert entry["validation_status"] == "NOT_RUN"


# ------------------------------------------------------- scope discipline

def test_neighbouring_families_keep_their_existing_refusals():
    # The rename is scoped to the either families; PITCHER_RECORD_WIN
    # and FIRST_HOME_RUN were NOT part of the decision package.
    for market in ("PITCHER_RECORD_WIN", "FIRST_HOME_RUN"):
        result = _run(_row(market))
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert GATE not in str(result.get("reason"))


def test_either_pitcher_k_stays_refused_out_of_scope():
    # DESIGN.md section 3.4: EITHER_PITCHER_K exists only as a census
    # slot (no engine branch, no catalog family, no settlement
    # market); it is excluded from this refinement and stays refused.
    result = _run(_row("EITHER_PITCHER_K"))
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result.get("model_probability") is None


def test_settlement_stays_fail_closed():
    from sportsedge.either_pitcher_settlement import (
        settle_either_pitcher)
    with pytest.raises(Exception) as exc:
        settle_either_pitcher(
            {}, market="EITHER_PITCHER_BB", entity_id="1|2", line=5.5,
            side="OVER")
    assert "EITHER_PITCHER_BOOK_SPECIFIC_SEMANTICS_REQUIRED" in str(
        exc.value)
