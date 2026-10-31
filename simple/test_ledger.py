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


# ---- #2987 concurrency regressions ----

def test_grade_refuses_when_file_changes_mid_grade_and_keeps_new_row(tmp_ledger, monkeypatch):
    """ChatGPT's #2987 interleaving: B lands on disk after grade's snapshot. B must survive."""
    rid_a = ledger.add(pick(side="A"))
    b_line = ledger._render([dict(id="bbbbbbbbbb", agent="x", model="M", sport="NFL", market="SPREAD",
                                  event="E", side="B", line="1", odds="-110", prob="0.5",
                                  captured_at="2026-10-31T07:00:00-05:00", source="s")]).split("\n", 1)[1]
    orig = ledger._render
    fired = []

    def racing_render(rows):
        out = orig(rows)
        if not fired:
            fired.append(1)
            with open(ledger.PATH, "a", newline="") as f:  # a writer that ignores the lock
                f.write(b_line)
        return out

    monkeypatch.setattr(ledger, "_render", racing_render)
    with pytest.raises(ledger.LedgerError, match="changed during grade"):
        ledger.grade(gr(rid_a))
    text = tmp_ledger.read_text()
    assert b_line in text
    assert {r["id"]: r["result"] for r in ledger._rows()} == {rid_a: "", "bbbbbbbbbb": ""}
    monkeypatch.setattr(ledger, "_render", orig)
    assert ledger.grade(gr(rid_a)) == rid_a  # clean retry succeeds
    assert b_line in tmp_ledger.read_text()


def test_lock_blocks_other_process(tmp_ledger):
    import subprocess, time
    ledger.add(pick(side="A"))
    code = ("import sys,argparse;sys.path.insert(0,%r);import ledger;ledger.PATH=%r;"
            "ledger.add(argparse.Namespace(agent='c',model='M',sport='NFL',market='SPREAD',event='E',side='Z',"
            "line='1',odds=-110.0,prob=0.5,captured_at='2026-10-31T07:00:00-05:00',source='s',note=''))"
            % (os.path.dirname(ledger.__file__), str(tmp_ledger)))
    with ledger._locked():
        p = subprocess.Popen([sys.executable, "-c", code])
        time.sleep(1.0)
        assert p.poll() is None  # waiting on the lock
        assert len(ledger._rows()) == 1
    assert p.wait(timeout=20) == 0
    assert len(ledger._rows()) == 2


def _worker(path, i):
    import argparse as ap
    ledger.PATH = path
    rid = ledger.add(ap.Namespace(agent="c", model="M", sport="NFL", market="SPREAD", event=f"E{i}",
                                  side="S", line="1", odds=-110.0, prob=0.5,
                                  captured_at="2026-10-31T07:00:00-05:00", source="s", note=""))
    ledger.grade(ap.Namespace(id=rid, result="W", final_source="f", close_line="", close_odds=None,
                              close_source=""))


def test_parallel_adds_and_grades_lose_nothing(tmp_ledger):
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_worker, args=(str(tmp_ledger), i)) for i in range(24)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    rows = ledger._rows()
    assert len(rows) == 24 and len({r["id"] for r in rows}) == 24
    assert all(r["result"] == "W" for r in rows)
