"""t257: a cited engine `sha` must be exactly the cleared head (t256 audit repro)."""
import json
from pathlib import Path

import pytest

from scripts import completion_gap_ledger as L

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
PRE_REFUSAL = "a5012ea8ce0cfc45f9b95801c8803d1ab7d24a2b"  # still prices LARGEST_LEAD
CLEARED = "ea53ee161a7b8f32cced1c44f7322e795e4ddcbf"
SITUATIONAL = "sportsedge/nfl_situational_empirical.py"


def _repro():
    bad = json.loads(json.dumps(POLICY))
    n = 0
    for e in bad["grok_branch_engines"]["NFL"].values():
        if e["engine_file"] == SITUATIONAL:
            assert e["cleared_head_sha"] == CLEARED
            e["sha"] = PRE_REFUSAL
            n += 1
    assert n >= 1
    return bad


def _all_ok(branch, sha):  # mocked remote: every sha is on its branch; heads are heads
    return "head" if sha != PRE_REFUSAL else "ancestor"


def test_recorded_policy_cites_cleared_heads_exactly():
    for key in L._GROK_KEYS:
        for entries in POLICY[key].values():
            for e in entries.values():
                assert e["sha"] == e["cleared_head_sha"]


def test_older_ancestor_sha_refused_by_verify_branch_shas():
    with pytest.raises(L.LedgerRefusal, match="CITED_SHA_NOT_CLEARED_HEAD"):
        L.verify_branch_shas(_repro(), resolver=_all_ok, file_resolver=lambda f, s: True)


def test_refused_before_any_remote_lookup():
    with pytest.raises(L.LedgerRefusal, match="CITED_SHA_NOT_CLEARED_HEAD"):
        L.verify_branch_shas(_repro(), resolver=lambda b, s: pytest.fail("looked up"))


def test_classify_never_emits_pre_refusal_sha():
    row = {"sport": "NFL", "market": "largest_lead", "blocker": "NO_ENGINE",
           "readiness": "NO_CANONICAL_PRICING_PATH", "validated_accuracy_in_this_audit": False}
    with pytest.raises(L.LedgerRefusal, match="CITED_SHA_NOT_CLEARED_HEAD"):
        L.classify(row, _repro())


def test_screen_entry_older_sha_refused():
    bad = json.loads(json.dumps(POLICY))
    e = bad["grok_branch_screen_engines"]["NFL"]["quarter_spread"]
    e["sha"] = "0" * 40
    with pytest.raises(L.LedgerRefusal, match="CITED_SHA_NOT_CLEARED_HEAD"):
        L.verify_branch_shas(bad, resolver=lambda b, s: "head", file_resolver=lambda f, s: True)
