"""RED (t211 re-audit @ 0978b66c, #2359): structural guard, zero false refusals.

status/reason/blocker must be exact members of repo-derived code sets (only
codes whose MEANING is promotion are excluded); identity fields and free text
are not word-screened; blocker_detail keys are pattern-checked; truthy
booleans are refused only in pricing_provenance and on authority keys.
"""
import json
from pathlib import Path

import pytest

from sportsedge import composite_card as cc
from sportsedge import promotion_screen as ps
from test_composite_audit_findings_20261015 import build, ou

ALLOW = json.loads((Path(__file__).resolve().parents[1] / "sportsedge"
                    / "composite_status_allowlist.json").read_text())

LEGIT = ["EITHER_PITCHER_MARGINAL_TAIL_ERROR", "PITCHER_HITS_ALLOWED", "FIRST_SCORING_PLAY",
         "EDGE_BELOW_FROZEN_FLOOR", "MISSING_OFFICIAL_DATE_FOR_HISTORY", "DUPLICATE_PLAY_ID"]
IN_REPO = LEGIT[1:]  # EITHER_PITCHER_* lives on its own unmerged branch


@pytest.mark.parametrize("code", LEGIT)
def test_legit_codes_are_not_promotion(code):
    assert not ps.promotion_meaning(code)


@pytest.mark.parametrize("code", IN_REPO)
def test_legit_repo_codes_accepted_as_reason_and_blocker(code):
    assert code in ALLOW["codes"]
    row = {"status": "PRICED_RESEARCH", "reason": code,
           "evaluation": {"blocker": code, "reason": code}}
    assert cc.authority_violation(row) is None


@pytest.mark.parametrize("code", ["ACTIONABLE", "LEAN", "RESEARCH_LEANS_AVAILABLE", "CLV_ELIGIBLE",
                                  "FIRST_EVALUATION_ALLOWED", "FORWARD_EVIDENCE_GATE_PASS",
                                  "RESEARCH_POSITIVE_EV", "RESEARCH_EDGE"])
def test_promotion_codes_excluded(code):
    assert ps.promotion_meaning(code)
    assert code not in ALLOW["statuses"] and code not in ALLOW["codes"]


def test_unknown_reason_code_refused_without_token_screen():
    assert cc.authority_violation({"status": "PRICED_RESEARCH", "reason": "SOMETHING_NEW"})


def test_blocker_detail_diagnostics_allowed():
    row = {"status": "PRICED_RESEARCH",
           "evaluation": {"blocker": "EDGE_BELOW_FROZEN_FLOOR",
                          "blocker_detail": {"sample_size": 40, "paired": True,
                                             "note": "Edge Rusher depth chart unverified",
                                             "unit": "yards"}}}
    assert cc.authority_violation(row) is None


@pytest.mark.parametrize("detail", [{"ev": 0.1}, {"ev_pct": 2}, {"expected_value_usd": 1},
                                    {"edge_bps": 3}, {"kelly_frac": 0.1}, {"stake_amt": 2},
                                    {"bet_size": 1}, {"wager": 1}, {"clv_eligible": True},
                                    {"model_authority": "yes"}, {"play": True}, {"playable": 1},
                                    {"official": True}, {"lock": True}, {"approved": True},
                                    {"actionable": True}, {"inner": {"playEligible": True}}])
def test_blocker_detail_authority_or_money_keys_refused(detail):
    row = {"status": "PRICED_RESEARCH", "evaluation": {"blocker": "EDGE_BELOW_FROZEN_FLOOR",
                                                       "blocker_detail": detail}}
    assert cc.authority_violation(row) is not None


def test_identity_and_free_text_not_word_screened():
    rows = ou("a", "G", 0, 1, player="Edge Rusher Lock", market="PLAYER_SACKS")
    comp = build(rows)
    assert {r["row_id"] for r in comp["rows"]} == {"ao", "au"}


def test_truthy_boolean_rule_scoped():
    ok = {"status": "PRICED_RESEARCH", "evaluation": {"blocker_detail": {"paired": True}}}
    assert cc.authority_violation(ok) is None
    bad = {"status": "PRICED_RESEARCH",
           "evaluation": {"pricing_provenance": {"lane": "X", "mechanism": True}}}
    assert cc.authority_violation(bad) is not None


def test_dropped_tokens():
    for t in ("TAIL", "TAKE", "FADE"):
        assert t not in ps.PROMOTION_TOKENS


@pytest.mark.parametrize("obj", [
    {"status": "PLAY NOW"}, {"status": "\uff30\uff2c\uff21\uff39"},
    {"evaluation": {"reason": "p.l.a.y"}}, {"evaluation": {"pricing_provenance": {"playEligible": True}}},
    {"stake_units": 2}, {"evPerDollar": 0.1}, {"evaluation": {"Status": "PLAY"}},
])
def test_earlier_bypasses_still_refused(obj):
    assert cc.authority_violation(obj) is not None
