"""Ledger v3: MLB pitcher markets already covered by committed frozen instruments.

PITCHER_K/BB/ER/HITS_ALLOWED are covered by docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md
(v2, frozen one-shot study); PITCHER_K additionally by the frozen K forward-validation
config. A duplicate forward-test config must not be built for them.
"""
import json
from pathlib import Path

import pytest

from scripts.completion_gap_ledger import LedgerRefusal, classify, gap_ledger

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
PITCHER = ("PITCHER_K", "PITCHER_BB", "PITCHER_ER", "PITCHER_HITS_ALLOWED")


def _row(market):
    return {"market": market, "sport": "MLB", "blocker": None,
            "readiness": "NO_FORWARD_TEST_CONFIG", "validated_accuracy_in_this_audit": False}


@pytest.mark.parametrize("market", PITCHER)
def test_pitcher_market_is_covered_not_buildable(market):
    g = classify(_row(market), POLICY)
    assert g["status"] == "COVERED_BY_COMMITTED_FROZEN_INSTRUMENT"
    assert g["score_area"] == "INFRASTRUCTURE"
    assert any("MLB_PITCHER_PROP_PROMOTION_PREREG.md" in r for r in g["record"])


def test_pitcher_k_also_cites_frozen_forward_config():
    g = classify(_row("PITCHER_K"), POLICY)
    assert any("mlb_pitcher_k_forward_validation_v1.json" in r for r in g["record"])


def test_covering_instruments_are_cross_checked_against_repo():
    for sport, entries in POLICY["covered_by_frozen_instrument"].items():
        for market, refs in entries.items():
            for ref in refs:
                text = (ROOT / ref["path"]).read_text(encoding="utf-8")
                assert ref["needle"] in text, (market, ref)


def test_missing_covering_needle_refuses():
    bad = json.loads(json.dumps(POLICY))
    bad["covered_by_frozen_instrument"]["MLB"]["PITCHER_BB"][0]["needle"] = "NOT_IN_FILE_XYZ"
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_NOT_FOUND"):
        classify(_row("PITCHER_BB"), bad)


def test_uncovered_config_gap_stays_buildable():
    g = classify({**_row("SOME_UNCOVERED"), "market": "SOME_UNCOVERED"}, POLICY)
    assert g["status"] == "BUILDABLE_NEEDS_SIBLING_RECONCILIATION"


def test_ledger_has_no_buildable_pitcher_gaps_and_confers_nothing():
    led = gap_ledger(offline=True)
    rows = {g["market"]: g for g in led["gaps"] if g["sport"] == "MLB"}
    for m in PITCHER:
        assert rows[m]["status"] == "COVERED_BY_COMMITTED_FROZEN_INSTRUMENT"
    assert led["validated_families_conferred"] == 0
    assert led["play_authority_conferred"] is False


def test_committed_ledger_matches_render():
    from scripts.completion_gap_ledger import render
    committed = (ROOT / "research" / "completion_gap_ledger_20261023.json").read_text(encoding="utf-8")
    assert committed == render({**gap_ledger(offline=True), "remote_shas_verified": True})
