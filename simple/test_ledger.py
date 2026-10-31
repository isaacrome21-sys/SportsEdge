"""Focused tests for simple/ledger.py fail-closed checks. Run: python -m pytest simple/test_ledger.py -q"""
import argparse
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import ledger  # noqa: E402


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    p = tmp_path / "ledger.csv"
    monkeypatch.setattr(ledger, "PATH", str(p))
    return p


def pick(**kw):
    d = dict(agent="claude", model="M", sport="NFL", market="SPREAD", event="A@B 2026-11-01",
             side="A", line="-3.5", odds=-110.0, prob=0.55,
             captured_at="2026-10-31T07:00:00-05:00", source="cap.json sha256=abc", note="")
    d.update(kw)
    return argparse.Namespace(**d)


def gr(rid, **kw):
    d = dict(id=rid, result="W", final_source="boxscore url", close_line="", close_odds=None, close_source="")
    d.update(kw)
    return argparse.Namespace(**d)


@pytest.mark.parametrize("kw", [dict(odds=-50.0), dict(odds=99.0), dict(odds=float("nan")),
                                dict(prob=0.0), dict(prob=1.0), dict(prob=1.7),
                                dict(captured_at="2026-10-31T07:00:00"), dict(captured_at="yesterday"),
                                dict(captured_at="2099-01-01T00:00:00+00:00"),
                                dict(source="   "), dict(side="")])
def test_add_refuses_bad_input_and_writes_nothing(tmp_ledger, kw):
    with pytest.raises(ledger.LedgerError):
        ledger.add(pick(**kw))
    assert not tmp_ledger.exists()


def test_add_appends_without_touching_existing_bytes(tmp_ledger):
    ledger.add(pick())
    before = tmp_ledger.read_bytes()
    assert ledger.add(pick(side="B", line="3.5")) is not None
    after = tmp_ledger.read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    assert ledger.add(pick()) is None  # duplicate skipped
    assert tmp_ledger.read_bytes() == after


def test_grade_requires_final_source_and_close_source(tmp_ledger):
    rid = ledger.add(pick())
    snap = tmp_ledger.read_bytes()
    with pytest.raises(ledger.LedgerError):
        ledger.grade(gr(rid, final_source=" "))
    with pytest.raises(ledger.LedgerError):
        ledger.grade(gr(rid, close_line="-3.5", close_odds=-120.0, close_source=""))
    with pytest.raises(ledger.LedgerError):
        ledger.grade(gr(rid, close_line="-4.5"))  # close line with no close odds
    with pytest.raises(ledger.LedgerError):
        ledger.grade(gr(rid, close_odds=-20.0, close_source="x"))
    assert tmp_ledger.read_bytes() == snap


def test_grade_fills_only_grade_fields_of_one_row(tmp_ledger):
    r1 = ledger.add(pick())
    r2 = ledger.add(pick(side="B", line="3.5", odds=-105.0))
    lines_before = tmp_ledger.read_text().split("\n")
    ledger.grade(gr(r1, close_line="-3.5", close_odds=-125.0, close_source="close.json sha256=def"))
    rows = {r["id"]: r for r in ledger._rows()}
    assert rows[r1]["result"] == "W" and rows[r1]["profit"] == "0.9091"
    assert rows[r1]["clv_prob"] == f"{ledger.american_to_prob(-125) - ledger.american_to_prob(-110):.4f}"
    assert rows[r1]["close_source"] == "close.json sha256=def" and rows[r1]["final_source"] == "boxscore url"
    lines_after = tmp_ledger.read_text().split("\n")
    changed = [i for i, (x, y) in enumerate(zip(lines_before, lines_after)) if x != y]
    assert len(changed) == 1
    assert ledger.grade(gr(r1, result="L")) is None  # already graded, untouched
    assert rows[r2]["result"] == ""


def test_grade_without_close_leaves_clv_blank(tmp_ledger):
    rid = ledger.add(pick())
    ledger.grade(gr(rid, result="P"))
    r = ledger._rows()[0]
    assert r["profit"] == "0" and r["clv_prob"] == "" and r["close_odds"] == ""


def test_old_header_is_widened_without_changing_values(tmp_ledger):
    old_cols = ledger.COLS[:-2]
    tmp_ledger.write_text(",".join(old_cols) + "\n" + ",".join(["x1"] + ["v"] * (len(old_cols) - 1)).replace(
        "v,v,v,v,v,v,v,v,v,v,v,v,v,v,v,v,v,v,v,v", ",".join(["v"] * 13 + [""] * 7)) + "\n")
    before = ledger._rows()
    ledger._ensure_header()
    after = ledger._rows()
    assert [{k: r[k] for k in old_cols} for r in after] == before
    assert all(r["close_source"] == "" and r["final_source"] == "" for r in after)
