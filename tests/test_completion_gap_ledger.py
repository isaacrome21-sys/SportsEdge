"""Completion gap ledger: structural gaps only; never confers validation."""
import json
from pathlib import Path

import pytest

from scripts.completion_gap_ledger import LedgerRefusal, gap_ledger, classify

ROOT = Path(__file__).resolve().parents[1]


def _row(market, sport="NFL", blocker=None, readiness="NO_CANONICAL_PRICING_PATH"):
    return {"market": market, "sport": sport, "blocker": blocker, "readiness": readiness,
            "validated_accuracy_in_this_audit": False}


POLICY = {"paused_markets": {"MLB": ["F5_TOTALS", "NRFI"]}, "schema": "SPORTSEDGE_COMPLETION_GAP_POLICY_V1"}


def test_no_engine_is_engines_gap_and_buildable_unless_paused():
    g = classify(_row("anytime_td", blocker="NO_ENGINE"), POLICY)
    assert (g["score_area"], g["status"]) == ("ENGINES", "BUILDABLE")


def test_paused_market_is_blocked_by_ruling_6():
    g = classify(_row("NRFI", "MLB", readiness="NO_FORWARD_TEST_CONFIG"), POLICY)
    assert g["status"] == "BLOCKED_RULING_6_FOCUS_PAUSE"


def test_no_validation_can_never_be_built():
    g = classify(_row("F5_RUN_LINE", "MLB", blocker="NO_VALIDATION"), {"paused_markets": {}})
    assert g["score_area"] == "VALIDATION"
    assert g["status"] == "BLOCKED_FORWARD_VERDICT_REQUIRED"


def test_no_data_and_no_quote_are_blocked_not_fabricated():
    assert classify(_row("first_td", blocker="NO_DATA"), POLICY)["status"] == "BLOCKED_MISSING_DATA"
    assert classify(_row("STOLEN_BASES", "MLB", blocker="NO_QUOTE"), POLICY)["status"] == "BLOCKED_MISSING_QUOTE"


def test_missing_forward_config_is_infrastructure():
    g = classify(_row("PITCHER_K", "MLB", readiness="NO_FORWARD_TEST_CONFIG"), POLICY)
    assert (g["score_area"], g["status"]) == ("INFRASTRUCTURE", "BUILDABLE_NEEDS_SIBLING_RECONCILIATION")


def test_priced_market_is_not_a_gap():
    assert classify(_row("BATTER_BB", "MLB", readiness="RESEARCH_PRICED_NOT_VALIDATED"), POLICY) is None


def test_unknown_blocker_refuses():
    with pytest.raises(LedgerRefusal):
        classify(_row("x", blocker="SOMETHING_NEW"), POLICY)


def test_validated_claim_in_input_refuses():
    bad = _row("x", blocker="NO_ENGINE"); bad["validated_accuracy_in_this_audit"] = True
    with pytest.raises(LedgerRefusal):
        classify(bad, POLICY)


def test_real_ledger_confers_nothing_and_is_deterministic():
    a, b = gap_ledger(), gap_ledger()
    assert a == b
    assert a["validated_families_conferred"] == 0
    assert a["play_authority_conferred"] is False
    assert a["score_points_awarded"] is None
    assert sum(a["counts_by_status"].values()) == len(a["gaps"])
    assert all(g["sport"] in {"MLB", "NFL"} for g in a["gaps"])


def test_committed_ledger_matches_regeneration():
    path = ROOT / "research" / "completion_gap_ledger_20261023.json"
    assert json.loads(path.read_text(encoding="utf-8")) == gap_ledger()


def test_owner_held_market_is_blocked():
    pol = {"paused_markets": {}, "owner_held_markets": {"MLB": ["EITHER_PITCHER_ER"]}}
    assert classify(_row("EITHER_PITCHER_ER", "MLB", blocker="NO_ENGINE"), pol)["status"] == "BLOCKED_OWNER_HOLD"
