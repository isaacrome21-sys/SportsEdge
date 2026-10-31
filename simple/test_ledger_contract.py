"""Pins the ledger.py WRITER CONTRACT limit (ChatGPT review 6548764884 on #2987).
Run: python -m pytest simple/test_ledger_contract.py -q"""
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


def test_unsupported_bypass_writer_after_cas_is_lost(tmp_ledger, monkeypatch):
    """A writer that skips ledger.py and appends between grade's final re-read and os.replace is lost.
    Unsupported by design: every writer must use ledger.py. If this test ever fails, the window was
    closed -- update the WRITER CONTRACT docstring."""
    rid_a = ledger.add(argparse.Namespace(
        agent="claude", model="M", sport="NFL", market="SPREAD", event="A@B 2026-11-01", side="A",
        line="-3.5", odds=-110.0, prob=0.55, captured_at="2026-10-31T07:00:00-05:00",
        source="cap.json sha256=abc", note=""))
    b_line = ledger._render([dict(id="bbbbbbbbbb", agent="x", model="M", sport="NFL", market="SPREAD",
                                  event="E", side="B", line="1", odds="-110", prob="0.5",
                                  captured_at="2026-10-31T07:00:00-05:00", source="s")]).split("\n", 1)[1]
    orig = ledger._atomic_write

    def bypass_then_write(text):
        with open(ledger.PATH, "a", newline="") as f:  # lock-bypassing writer, after the re-read
            f.write(b_line)
        orig(text)

    monkeypatch.setattr(ledger, "_atomic_write", bypass_then_write)
    assert ledger.grade(argparse.Namespace(id=rid_a, result="W", final_source="boxscore url",
                                           close_line="", close_odds=None, close_source="")) == rid_a
    assert b_line not in tmp_ledger.read_text()
    assert [r["id"] for r in ledger._rows()] == [rid_a]
