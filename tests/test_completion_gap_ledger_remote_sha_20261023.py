"""Grok-branch engine SHAs must be real commits on the named remote branch."""
import json
import os
from pathlib import Path

import pytest

from scripts.completion_gap_ledger import LedgerRefusal, verify_branch_shas

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))


def _fake(status_by_pair):
    def resolve(branch, sha):
        return status_by_pair.get((branch, sha), "missing")
    return resolve


def _pairs():
    return {(e["branch"], e["sha"]) for s in POLICY["grok_branch_engines"].values() for e in s.values()}


def test_all_recorded_pairs_pass_when_resolver_confirms():
    res = verify_branch_shas(POLICY, resolver=_fake({p: "on_branch" for p in _pairs()}))
    assert res == sorted(_pairs())


def test_sha_not_on_branch_refuses():
    pairs = _pairs(); first = sorted(pairs)[0]
    fake = {p: "on_branch" for p in pairs}; fake[first] = "missing"
    with pytest.raises(LedgerRefusal, match="GROK_BRANCH_SHA_NOT_ON_REMOTE"):
        verify_branch_shas(POLICY, resolver=_fake(fake))


def test_forty_hex_lookalike_refuses():
    bad = json.loads(json.dumps(POLICY))
    bad["grok_branch_engines"]["NFL"]["team_sacks"]["sha"] = "f" * 40
    fake = {p: "on_branch" for p in _pairs()}
    with pytest.raises(LedgerRefusal, match="GROK_BRANCH_SHA_NOT_ON_REMOTE"):
        verify_branch_shas(bad, resolver=_fake(fake))


@pytest.mark.parametrize("sha", ["abc", "g" * 40, None, 123])
def test_malformed_sha_refuses_before_any_lookup(sha):
    bad = json.loads(json.dumps(POLICY))
    bad["grok_branch_engines"]["NFL"]["team_sacks"]["sha"] = sha
    with pytest.raises(LedgerRefusal, match="GROK_BRANCH_SHA_MALFORMED"):
        verify_branch_shas(bad, resolver=lambda b, s: pytest.fail("looked up"))


def test_branch_must_be_grok():
    bad = json.loads(json.dumps(POLICY))
    bad["grok_branch_engines"]["NFL"]["team_sacks"]["branch"] = "main"
    with pytest.raises(LedgerRefusal, match="GROK_BRANCH_REQUIRED"):
        verify_branch_shas(bad, resolver=lambda b, s: "on_branch")


@pytest.mark.skipif(os.environ.get("SPORTSEDGE_LEDGER_REMOTE_CHECK") != "1",
                    reason="network check; set SPORTSEDGE_LEDGER_REMOTE_CHECK=1")
def test_real_remote_confirms_every_recorded_sha():
    assert verify_branch_shas(POLICY) == sorted(_pairs())
