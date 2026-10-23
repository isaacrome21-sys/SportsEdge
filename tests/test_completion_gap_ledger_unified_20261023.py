"""Unified ledger: covering-instrument hardening (paths, citations, markers, order)."""
import json
from pathlib import Path

import pytest

from scripts.completion_gap_ledger import LedgerRefusal, classify

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
PREREG = "docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md"
KCFG = "config/research/mlb_pitcher_k_forward_validation_v1.json"


def _row(market, sport="MLB"):
    return {"market": market, "sport": sport, "blocker": None,
            "readiness": "NO_FORWARD_TEST_CONFIG", "validated_accuracy_in_this_audit": False}


def _with(refs, market="PITCHER_BB"):
    p = json.loads(json.dumps(POLICY))
    p["covered_by_frozen_instrument"]["MLB"][market] = refs
    return p


def test_every_covering_ref_declares_a_marker_kind():
    for entries in POLICY["covered_by_frozen_instrument"].values():
        for refs in entries.values():
            assert all(r["marker"] in ("SCOPE", "FREEZE") for r in refs)


@pytest.mark.parametrize("path", ["../outside.md", "/etc/hostname", "docs/../../x.md",
                                  "docs/../../../etc/passwd"])
def test_path_outside_repo_refuses(path):
    ref = {"path": path, "needle": "x", "marker": "SCOPE"}
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_PATH_ESCAPE"):
        classify(_row("PITCHER_BB"), _with([ref]))


@pytest.mark.parametrize("ref", [
    "docs/x.md", None, 7, {}, {"path": PREREG}, {"needle": "x", "marker": "SCOPE"},
    {"path": PREREG, "needle": None, "marker": "SCOPE"},
    {"path": 3, "needle": "x", "marker": "SCOPE"},
    {"path": PREREG, "needle": "Pitcher props", "marker": "VIBES"},
    {"path": PREREG, "needle": "Pitcher props"},
])
def test_malformed_citation_refuses_with_code(ref):
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_CITATION_MALFORMED"):
        classify(_row("PITCHER_BB"), _with([ref]))


@pytest.mark.parametrize("bad", [{"PITCHER_BB": "x"}, ["x"], "x"])
def test_malformed_citation_container_refuses_with_code(bad):
    p = json.loads(json.dumps(POLICY)); p["covered_by_frozen_instrument"]["MLB"] = bad
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_CITATION"):
        classify(_row("PITCHER_BB"), p)


def test_scope_needle_outside_scope_section_refuses():
    # Present in the prereg, but in the "What this study does not do" section.
    ref = {"path": PREREG, "needle": "Batter props are out of scope", "marker": "SCOPE"}
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_NOT_A_MARKER"):
        classify(_row("PITCHER_BB"), _with([ref]))


def test_scope_needle_must_name_the_market():
    ref = {"path": PREREG, "needle": "Pitcher props (PITCHER_K", "marker": "SCOPE"}
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_NOT_A_MARKER"):
        classify(_row("PITCHER_BB"), _with([ref]))


def test_freeze_needle_must_be_the_frozen_status_line():
    ref = {"path": KCFG, "needle": '"schema"', "marker": "FREEZE"}
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_NOT_A_MARKER"):
        classify(_row("PITCHER_K"), _with([ref], "PITCHER_K"))


def test_freeze_marker_on_non_frozen_or_non_json_refuses():
    ref = {"path": PREREG, "needle": "pre-registration", "marker": "FREEZE"}
    with pytest.raises(LedgerRefusal, match="COVERING_INSTRUMENT_NOT_A_MARKER"):
        classify(_row("PITCHER_K"), _with([ref], "PITCHER_K"))


def test_covered_is_classified_after_pause_and_hold():
    p = json.loads(json.dumps(POLICY))
    p["covered_by_frozen_instrument"]["MLB"]["NRFI"] = POLICY["covered_by_frozen_instrument"]["MLB"]["PITCHER_K"]
    p["owner_held_markets"]["MLB"]["PITCHER_BB"] = p["owner_held_markets"]["MLB"]["EITHER_PITCHER_ER"]
    assert classify(_row("NRFI"), p)["status"] == "BLOCKED_RULING_6_FOCUS_PAUSE"
    assert classify(_row("PITCHER_BB"), p)["status"] == "BLOCKED_OWNER_HOLD"
    assert classify(_row("PITCHER_ER"), p)["status"] == "COVERED_BY_COMMITTED_FROZEN_INSTRUMENT"
