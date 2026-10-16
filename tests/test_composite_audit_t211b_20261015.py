"""RED regressions for the t211 re-audit @ 8a794cbd (#2359, research only).

* promotion tokens extended (ACTIONABLE, LEAN/LEANS, ELIGIBLE, ALLOWED,
  gate-context PASS, POSITIVE_EV, EDGE, ...); negation only by the token
  immediately before; allowlist marked PENDING_OWNER_CURATION;
* any *_eligible / *_authority key truthy at any depth is refused;
* every string value is screened; EV-like keys refused by pattern;
* build_composite validates any evaluator's ``evaluation`` dict;
* no authority keys allowed at the child top level.
"""
import json
from pathlib import Path

import pytest

from sportsedge import composite_card as cc
from sportsedge.promotion_screen import promotes
from test_composite_audit_findings_20261015 import build, ou

ALLOWLIST = Path(__file__).resolve().parents[1] / "sportsedge" / "composite_status_allowlist.json"


@pytest.mark.parametrize("s", [
    "ACTIONABLE", "LEAN", "LEANS", "lean ", " Leans", "RESEARCH_LEANS_AVAILABLE",
    "CLV_ELIGIBLE", "FIRST_EVALUATION_ALLOWED", "FORWARD_EVIDENCE_GATE_PASS",
    "RESEARCH_POSITIVE_EV", "RESEARCH_EDGE", "NO_X_PLAY", "NOT_A_PLAY",
    "RECOMMENDED", "APPROVED_FOR_ACTION", "best bet", "+EV lean"])
def test_promotion_tokens(s):
    assert promotes(s)


@pytest.mark.parametrize("s", ["NO_PLAY", "NOT_ELIGIBLE", "NO_EDGE", "NO_LEANS",
                               "PRICED_RESEARCH", "WATCH_NFL_NO_VERIFIED_CONTEXT",
                               "PLAYER_PASS_YARDS", "OVER", "PASS"])
def test_non_promotions(s):
    assert not promotes(s)


def test_allowlist_has_no_promotion_and_is_pending_owner_curation():
    doc = json.loads(ALLOWLIST.read_text())
    assert doc["curation_state"] == "PENDING_OWNER_CURATION"
    for bad in ("ACTIONABLE", "LEAN", "RESEARCH_LEANS_AVAILABLE", "CLV_ELIGIBLE",
                "FORWARD_EVIDENCE_GATE_PASS",  # FIRST_EVALUATION_ALLOWED allowed (t211e owner)
                "RESEARCH_POSITIVE_EV", "RESEARCH_EDGE"):
        assert bad not in doc["statuses"]
    from sportsedge.promotion_screen import promotion_meaning  # t211d: exclusion by meaning
    assert not [s for s in doc["statuses"] + doc["codes"] if promotion_meaning(s)]


@pytest.mark.parametrize("obj", [
    {"play_eligible": True}, {"evaluation": {"pricing_provenance": {"clv_eligible": True}}},
    {"x": [{"model_authority": 1}]}, {"Play_Eligible": 1},
])
def test_eligible_and_authority_keys_any_depth(obj):
    assert cc.authority_violation(obj) is not None


@pytest.mark.parametrize("obj", [
    {"verdict": "LEAN"}, {"action": "BET NOW"}, {"tier": "ACTIONABLE"},
    {"reason": "positive EV edge"}, {"evaluation": {"note": ["best bet"]}},
    {"ev_pct": 3}, {"expected_value_usd": 1}, {"edge_bps": 20}, {"kelly_half": 0.1},
    {"Expected_Value": 0.2},
])
def test_string_values_and_ev_key_patterns(obj):
    assert cc.authority_violation(obj) is not None


def test_benign_values_pass():
    assert cc.authority_violation({"status": "PRICED_RESEARCH", "reason": "WATCH_NFL_NO_VERIFIED_CONTEXT",
                                   "evaluation": {"reason_detail": "no verified context",
                                                  "pricing_provenance": {"play_eligible": False}}}) is None


def _ev_with(evaluation, **top):
    def ev(g, rows, as_of, ctx):
        return {"as_of_utc": as_of, "game_id": g,
                "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"],
                          "status": "PRICED_RESEARCH",
                          "quote_captured_at": r["quote_captured_at"],
                          "evaluation": evaluation, **top} for r in rows]}
    return ev


def test_build_validates_any_evaluator_evaluation_keys():
    with pytest.raises(cc.CompositeError, match=cc.CHILD_EVALUATION_FIELD_NOT_ALLOWED):
        build(ou("a", "G", 0, 1), evaluator=_ev_with({"mystery": 1}))


def test_build_refuses_nested_promotion_value():
    with pytest.raises(cc.CompositeError):
        build(ou("a", "G", 0, 1), evaluator=_ev_with({"reason": "strong lean"}))


@pytest.mark.parametrize("key", ["eligible", "official_authority", "staking_authority",
                                 "model_p_authority", "play", "stake", "promotion", "official"])
def test_authority_keys_not_allowed_at_top_level(key):
    assert key not in cc._CHILD_ALLOWED_FIELDS
    with pytest.raises(cc.CompositeError):
        build(ou("a", "G", 0, 1), evaluator=_ev_with({}, **{key: False}))
