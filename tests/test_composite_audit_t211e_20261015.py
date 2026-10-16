"""RED (t211 re-audit @ 8f4e91f9, #2359).

1. reason_detail / blocker_detail are diagnostics only: never rendered or
   consumed by render / quote audit / grading / pitcher-K; broadened key
   patterns refuse only numeric or boolean-truthy values; parameter-name
   suffixes (_id, _floor, _cap, _type, _policy, _policy_id) are exempt.
2. Promotion RESULTS (PASS, QUALIFIED, OK, READY_FOR_AUTHORITY, PROMOTION,
   LIVE_MODEL_OK) are promotion unless the IMMEDIATELY preceding token negates;
   refusal words elsewhere grant no immunity.
3. EITHER_PITCHER_MARGINAL_TAIL_ERROR is in the code set (owner t207u/t208u).
4. FIRST_EVALUATION_ALLOWED is allowed (scheduling gate).
"""
import json
from pathlib import Path

import pytest

from sportsedge import composite_card as cc
from sportsedge import composite_run_it as cri
from sportsedge import promotion_screen as ps
from test_composite_audit_findings_20261015 import build, ou

ALLOW = json.loads((Path(__file__).resolve().parents[1] / "sportsedge"
                    / "composite_status_allowlist.json").read_text())
SECRET_R = "ZZ_REASON_DETAIL_SENTINEL_42"
SECRET_B = "ZZ_BLOCKER_DETAIL_SENTINEL_77"


def _detail_eval(game_id, rows, as_of, context):
    return {"as_of_utc": as_of, "game_id": game_id,
            "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"],
                      "status": "PRICED_RESEARCH", "quote_captured_at": r["quote_captured_at"],
                      "evaluation": {"status": "PRICED_RESEARCH",
                                     "blocker": "EDGE_BELOW_FROZEN_FLOOR",
                                     "reason_detail": SECRET_R,
                                     "blocker_detail": {"note": SECRET_B, "sample_size": 41,
                                                        SECRET_B.lower(): "x"}}}
                     for r in rows]}


def _comp():
    return build(ou("a", "G", 0, 1), evaluator=_detail_eval)


def test_rendered_card_contains_no_detail_content():
    comp = _comp()
    md = cri.render_composite_markdown(comp, pin=comp["manifest_digest"], run_url="")
    for s in (SECRET_R, SECRET_B, SECRET_B.lower(), "41", "reason_detail", "blocker_detail"):
        assert s not in md


def test_quote_audit_contains_no_detail_content():
    comp = _comp()
    out = json.dumps(cri.composite_quote_audit(comp, pin=comp["manifest_digest"]))
    assert SECRET_R not in out and SECRET_B not in out and "_detail" not in out


def test_grading_ignores_details():
    comp = _comp()
    g = cc.grade_composite(comp, {}, pin=comp["manifest_digest"])
    assert SECRET_R not in json.dumps(g, default=str) and SECRET_B not in json.dumps(g, default=str)


def test_diagnostic_only_fields_declared():
    assert set(cc.DIAGNOSTIC_ONLY_FIELDS) == {"reason_detail", "blocker_detail"}
    row = {"evaluation": {"reason_detail": "x", "blocker_detail": {}, "status": "S"}}
    assert cc.strip_diagnostics(row) == {"evaluation": {"status": "S"}}


def _bd(detail):
    return {"status": "PRICED_RESEARCH",
            "evaluation": {"blocker": "EDGE_BELOW_FROZEN_FLOOR", "blocker_detail": detail}}


@pytest.mark.parametrize("key", ["units", "unit_count", "risk_units", "edge", "risk_amount",
                                 "riskPct", "to_win", "roi", "is_official", "officialFlag",
                                 "ok_to_post", "best_bet"])
@pytest.mark.parametrize("val", [1, 0.5, True])
def test_broadened_patterns_refuse_numeric_or_true(key, val):
    assert cc.authority_violation(_bd({key: val})) is not None


@pytest.mark.parametrize("key", ["units", "edge", "roi", "best_bet", "model_authority"])
@pytest.mark.parametrize("val", [False, None])  # t211f: strings in detail fields now refuse
def test_patterns_ignore_strings_and_false(key, val):
    assert cc.authority_violation(_bd({key: val})) is None


@pytest.mark.parametrize("key", ["bet_id", "stake_policy_id", "official_game_id"])
def test_parameter_suffixes_exempt(key):
    # t211f: inside detail fields only _id rescues a money/authority base word;
    # edge_floor_pp, kelly_cap, wager_type, stake_policy now refuse there.
    assert cc.authority_violation(_bd({key: 2})) is None


@pytest.mark.parametrize("code", ["CONDITIONAL_PASS", "SHADOW_QUALIFIED", "MODEL_OK",
                                  "LIVE_MODEL_OK", "PROBATION_TRANSITION_READY_FOR_AUTHORITY_REVIEW",
                                  "PROMOTION_EVIDENCE_REQUIRED", "HOLDOUT_PASS",
                                  "OFFICIAL_CONFIRMATION_MISSING"])
def test_promotion_results_excluded_without_immediate_negation(code):
    assert ps.promotion_meaning(code)
    assert code not in ALLOW["codes"] and code not in ALLOW["statuses"]


@pytest.mark.parametrize("code", ["NOT_QUALIFIED", "NO_PASS", "NOT_OK", "NO_PROMOTION",
                                  "MISSING_PASS", "BELOW_QUALIFIED"])
def test_immediate_negation_negates(code):
    assert not ps.promotion_meaning(code)


@pytest.mark.parametrize("code", ["EITHER_PITCHER_MARGINAL_TAIL_ERROR", "PITCHER_HITS_ALLOWED",
                                  "FIRST_SCORING_PLAY", "EDGE_BELOW_FROZEN_FLOOR",
                                  "MISSING_OFFICIAL_DATE_FOR_HISTORY", "DUPLICATE_PLAY_ID",
                                  "FIRST_EVALUATION_ALLOWED"])
def test_earlier_legit_codes_still_pass(code):
    assert not ps.promotion_meaning(code)
    assert code in ALLOW["codes"] or code in ALLOW["statuses"]
    assert cc.authority_violation({"status": "PRICED_RESEARCH", "reason": code,
                                   "evaluation": {"blocker": code}}) is None


def test_either_pitcher_owner_approved_explicit():
    assert "EITHER_PITCHER_MARGINAL_TAIL_ERROR" in ALLOW["owner_approved_codes"]
