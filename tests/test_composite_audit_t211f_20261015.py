"""RED (t211 re-audit @ 03e6e26c, MEDIUM, #2359).

(a) reason_detail / blocker_detail never reach ANY emitted card: stdout JSON,
    --output, supersede() output, render. They may go only to a separate,
    labeled NON-CARD diagnostics file.
(b) inside the detail fields, exemption suffixes do not rescue money/authority
    base words, defense-in-depth size tokens refuse, and string values on
    money/authority keys refuse.
(c) EARLY_SEASON_FAVORITE_HARD_PASS is not promotion.
"""
import json

import pytest

from _capture_receipt_fixtures import write_store
from artifacts import run_it_full as full
from sportsedge import composite_card as cc
from sportsedge import composite_run_it as cri
from sportsedge import promotion_screen as ps
from test_composite_audit_findings_20261015 import _clock_for, build, ou
from test_composite_audit_t211e_20261015 import SECRET_B, SECRET_R, _detail_eval

DETAIL_STRINGS = (SECRET_R, SECRET_B, SECRET_B.lower(), "reason_detail", "blocker_detail")


def _assert_clean(text):
    for s in DETAIL_STRINGS:
        assert s not in text, s


def test_build_composite_rows_carry_no_detail_and_sink_receives_it():
    sink = []
    rows = ou("a", "G", 0, 1)
    from _capture_receipt_fixtures import receipts_for
    comp = cc.build_composite(rows, evaluator=_detail_eval, revision="r",
                              publication_clock="2026-10-15T23:10:00Z",
                              receipts=receipts_for(rows), clock=_clock_for(rows),
                              diagnostics_sink=sink)
    assert comp["rows"]
    _assert_clean(json.dumps(comp))
    assert sink and all(d["artifact_kind"] == cc.DIAGNOSTICS_KIND for d in sink)
    assert SECRET_R in json.dumps(sink)


def test_verify_refuses_card_carrying_detail():
    comp = build(ou("a", "G", 0, 1), evaluator=_detail_eval)
    comp["rows"][0].setdefault("evaluation", {})["reason_detail"] = "x"
    assert not cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"]


def test_supersede_output_has_no_detail():
    c1 = build(ou("a", "G", 0, 1), evaluator=_detail_eval)
    c2 = build(ou("b", "G", 30, 31), evaluator=_detail_eval)
    out = cri.supersede([c1, c2], pins=[c1["manifest_digest"], c2["manifest_digest"]])
    _assert_clean(json.dumps(out))


def test_render_has_no_detail():
    c = build(ou("a", "G", 0, 1), evaluator=_detail_eval)
    _assert_clean(cri.render_composite_markdown(c, pin=c["manifest_digest"]))


def test_cli_stdout_output_and_diagnostics_file(tmp_path, monkeypatch, capsys):
    rows = ou("a", "G", 0, 1)
    root, pin = write_store(rows, tmp_path / "store")
    from sportsedge.capture_preflight import load_capture_receipts
    rc = load_capture_receipts(root, manifest_sha256=pin)
    for r in rows:  # what the live capture adapter records at read time
        r["verification"]["raw_sha256"] = rc[r["verification"]["read_id"]]["raw_sha256"]
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"lines": rows}))
    monkeypatch.setattr(cri, "run_full_evaluator", lambda *a, **k: _detail_eval)
    orig = cri.run_composite
    monkeypatch.setattr(cri, "run_composite",
                        lambda *a, **k: orig(*a, **{**k, "clock": _clock_for(rows)}))
    out, diag = tmp_path / "card.json", tmp_path / "diag.json"
    full.main(["--lines", str(lines), "--composite", "--no-fetch", "--output", str(out),
               "--diagnostics-output", str(diag),
               "--capture-receipts-dir", str(root), "--capture-receipts-manifest-sha256", pin])
    stdout = capsys.readouterr().out
    card = json.loads(out.read_text())
    assert card["rows"], [r["refusal_code"] for r in card["refused"]]
    _assert_clean(stdout)
    _assert_clean(out.read_text())
    d = json.loads(diag.read_text())
    assert d["artifact_kind"] == cc.DIAGNOSTICS_KIND and d["is_card"] is False
    assert SECRET_R in diag.read_text()


def _bd(detail):
    return {"status": "PRICED_RESEARCH",
            "evaluation": {"blocker": "EDGE_BELOW_FROZEN_FLOOR", "blocker_detail": detail}}


@pytest.mark.parametrize("detail", [
    {"stake_cap": 2}, {"kelly_cap": 0.25}, {"official_type": True}, {"ok_to_bet_type": 1},
    {"units_policy": 1}, {"units_pp": 2}, {"u": 1}, {"size": 2}, {"bet_sizing": 1},
    {"amount": 5}, {"dollars": 10}, {"bankroll": 100}, {"units": "2u"}, {"stake": "1 unit"},
    {"edge": "4%"}, {"inner": {"kelly_cap": 1}},
])
def test_detail_money_keys_refused(detail):
    assert cc.authority_violation(_bd(detail)) is not None
    ev = {"status": "PRICED_RESEARCH", "evaluation": {"reason_detail": detail}}
    assert cc.authority_violation(ev) is not None


@pytest.mark.parametrize("detail", [{"sample_size": 40}, {"paired": True},
                                    {"note": "Edge Rusher"}, {"bet_id": "abc"}])
def test_detail_benign_still_passes(detail):
    assert cc.authority_violation(_bd(detail)) is None


def test_hard_pass_not_promotion():
    assert not ps.promotion_meaning("EARLY_SEASON_FAVORITE_HARD_PASS")
