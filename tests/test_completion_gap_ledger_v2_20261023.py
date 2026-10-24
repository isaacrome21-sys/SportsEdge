"""Ledger v2: engine-exists cross-check, cited records, exact bytes, consistency."""
import json
from pathlib import Path

import pytest

from scripts.completion_gap_ledger import LedgerRefusal, classify, gap_ledger, render
from sportsedge.canonical_coverage import MARKET_RESOLUTIONS

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))


def _row(market, sport="NFL", blocker="NO_ENGINE", readiness="NO_CANONICAL_PRICING_PATH"):
    return {"market": market, "sport": sport, "blocker": blocker, "readiness": readiness,
            "validated_accuracy_in_this_audit": False}


def test_coverage_engine_reference_means_engine_exists_not_wired():
    g = classify(_row("fg_made"), POLICY)
    assert g["status"] == "ENGINE_EXISTS_NOT_WIRED"
    assert "NFL_KICKING_EMPIRICAL" in g["engine_ref"]


def test_existing_engine_code_is_cross_checked_against_repo():
    for sport, entries in POLICY["existing_engine_code"].items():
        for market, ref in entries.items():
            text = (ROOT / ref["path"]).read_text(encoding="utf-8")
            assert ref["needle"] in text, (market, ref)
            assert classify(_row(market, sport), POLICY)["status"] == "ENGINE_EXISTS_NOT_WIRED"


def test_existing_engine_code_with_missing_needle_refuses(tmp_path):
    bad = json.loads(json.dumps(POLICY))
    bad["existing_engine_code"]["NFL"]["player_sacks"]["needle"] = "NOT_IN_FILE_XYZ"
    with pytest.raises(LedgerRefusal, match="ENGINE_CODE_NOT_FOUND"):
        classify(_row("player_sacks"), bad)


def test_grok_branch_engine_status():
    g = classify(_row("team_sacks"), POLICY)
    assert g["status"] == "ENGINE_ON_GROK_BRANCH_NOT_MERGED"
    assert len(g["engine_ref"]["sha"]) == 40


def test_every_no_engine_without_any_engine_is_buildable():
    ledger = gap_ledger(offline=True)
    for g in ledger["gaps"]:
        if g["status"] == "BUILDABLE":
            res = MARKET_RESOLUTIONS[(g["sport"], g["market"])]
            assert not res.get("engine")


def test_every_pause_and_hold_cites_an_existing_record():
    for key in ("paused_markets", "owner_held_markets"):
        for sport, entries in POLICY[key].items():
            for market, rec in entries.items():
                path, _, anchor = rec.partition("#")
                text = (ROOT / path).read_text(encoding="utf-8")
                assert anchor and f"## {anchor}" in text, rec
                assert market in text, (market, rec)


def test_uncited_pause_refuses():
    bad = json.loads(json.dumps(POLICY)); bad["paused_markets"]["MLB"]["NRFI"] = ""
    with pytest.raises(LedgerRefusal, match="RECORD_CITATION_REQUIRED"):
        classify(_row("NRFI", "MLB", blocker=None, readiness="NO_FORWARD_TEST_CONFIG"), bad)


@pytest.mark.parametrize("blocker,readiness", [
    ("NO_ENGINE", "RESEARCH_PRICED_NOT_VALIDATED"),
    ("NO_DATA", "NO_FORWARD_TEST_CONFIG"),
    (None, "NO_CANONICAL_PRICING_PATH"),
])
def test_blocker_contradicting_readiness_refuses(blocker, readiness):
    with pytest.raises(LedgerRefusal, match="BLOCKER_READINESS_CONTRADICTION"):
        classify(_row("x", blocker=blocker, readiness=readiness), POLICY)


def test_committed_ledger_matches_regeneration_byte_for_byte():
    path = ROOT / "research" / "completion_gap_ledger_20261023.json"
    assert path.read_bytes() == render({**gap_ledger(offline=True), "remote_shas_verified": True}).encode("utf-8")
