"""Fail-closed Phase 7 research-edge provenance contract.

These are synthetic offline fixtures; no market quotes are fetched and
nothing here grants model validation, promotion or execution authority.
"""
from sportsedge.market_coverage import finalize_research_row
from sportsedge.pricing_provenance import (
    LANE_INDEPENDENT, LANE_MARKET_ANCHORED, UNDETERMINED_STATUS,
    ANCHORED_WATCH_STATUS, PLAY_SURFACE_STATUSES,
    apply_play_gate,
)


def _phase7_positive_ev():
    return finalize_research_row(
        sport="NFL", game="Away @ Home", selection="OVER",
        market="TOTAL_1Q", price=-110, dec=1.909090909,
        line=10.5, win=0.75, push=0.0,
        home_mean=23.0, away_mean=20.0,
        kickoff_iso="2026-10-19T20:15:00+00:00",
        context={"home_rating": 0.0, "away_rating": 0.0},
        context_notes=["NO_FETCH_MANUAL_MODE_NO_PUBLIC_CONTEXT"],
        model_family="FREE_COVERAGE_EXTENSION_UNVALIDATED",
    )


def test_phase7_status_declared_a_play_surface():
    assert "RESEARCH_EDGE" in PLAY_SURFACE_STATUSES
    row = _phase7_positive_ev()
    assert row["status"] == "RESEARCH_EDGE"
    assert row["research_only"] is True
    assert row["model_validation"] == "NOT_PROVEN_VS_CLOSE"


def test_phase7_unverified_edge_fails_closed_on_canonical_gate():
    row = _phase7_positive_ev()
    before_ev = row["ev_per_dollar"]
    assert row.get("pricing_provenance") is None
    assert apply_play_gate([row]) == 1
    assert row["status"] == UNDETERMINED_STATUS
    assert row["pricing_provenance"]["lane"] == "UNDETERMINED"
    assert row["play_blocked_reason"] == "PROVENANCE_UNDETERMINED"
    assert row["ev_per_dollar"] == before_ev  # audit math preserved
    assert row["official_authority"] is False
    assert row["staking_authority"] is False


def test_phase7_market_anchored_edge_becomes_watch_without_fair_edge():
    row = _phase7_positive_ev()
    row["pricing_provenance"] = {
        "lane": LANE_MARKET_ANCHORED,
        "mechanism": "MARKET_SHRINK_15PCT",
        "source": "SYNTHETIC_ANCHORED_TEST",
        "play_eligible": False,
    }
    assert apply_play_gate([row]) == 1
    assert row["status"] == ANCHORED_WATCH_STATUS
    assert row["ev_presentation"] == "ANCHORED_RESEARCH_ONLY_NOT_A_PLAY"


def test_independent_labeled_research_edge_is_not_automatically_promoted():
    row = _phase7_positive_ev()
    row["pricing_provenance"] = {
        "lane": LANE_INDEPENDENT,
        "mechanism": None,
        "source": "SYNTHETIC_PROVENANCE_TEST",
        "play_eligible": True,
    }
    assert apply_play_gate([row]) == 0
    assert row["status"] == "RESEARCH_EDGE"
    # The provenance gate establishes *only* model-blind origin.
    # Historical validation, exact DK quote pairing and official deployment
    # remain distinct gates; this regression grants none of them.
    assert row["research_only"] is True
    assert row["official_authority"] is False
    assert row["model_p_authority"] is False


def test_phase7_status_without_probability_also_fails_closed():
    row = {"status": "RESEARCH_EDGE", "research_only": True}
    assert apply_play_gate([row]) == 1
    assert row["status"] == UNDETERMINED_STATUS


def test_nonedge_below_threshold_never_upgrades_into_candidate():
    row = _phase7_positive_ev()
    row["status"] = "BELOW_THRESHOLD"
    assert apply_play_gate([row]) == 0
    assert row["status"] == "BELOW_THRESHOLD"
