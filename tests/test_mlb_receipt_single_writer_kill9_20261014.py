"""t143: one authoritative receipt writer (#2229 BEGIN/COMMIT/ABORT) + deterministic kill-9.

Owner ruling 2026-10-14: #2229 is the receipt journal; #2221's unjournaled writer is removed.
A raw receipt without a committed journal record must be refused after restart and is never
repaired, backfilled or admitted.
"""
from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "sportsedge"
NOW = datetime(2026, 10, 14, 11, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
WRITE_PRIMITIVES = {"_durable_receipt_write", "_append_line_fsync"}

CHILD = textwrap.dedent("""
    import os, sys, time
    from datetime import datetime, timezone
    from pathlib import Path
    from unittest.mock import patch
    sys.path.insert(0, {repo!r})
    from sportsedge import mlb_source as ms
    NOW = datetime(2026, 10, 14, 11, tzinfo=timezone.utc)
    stage = {stage!r}
    real_write = ms._durable_receipt_write
    def write(path, data, *, append):
        real_write(path, data, append=append)
        name = Path(path).name
        hit = (stage == "after_raw" and not append) or \\
              (stage == "after_journal" and append and name == ms.RECEIPT_JOURNAL_NAME)
        if hit:
            sys.stdout.write("READY\\n"); sys.stdout.flush()
            time.sleep(120)
    with patch.object(ms, "_trusted_now", return_value=NOW), \\
         patch.object(ms, "_durable_receipt_write", write):
        rec = ms.MLBSourceCapture(Path({root!r}))
        if {prior!r}:
            rec.record(url="https://example.test/prior", raw=b'{{"p":1}}',
                       fetch_started_at=NOW, received_at=NOW)
        rec.record(url="https://example.test/victim", raw=b'{{"v":1}}',
                   fetch_started_at=NOW, received_at=NOW)
    sys.stdout.write("FINISHED\\n"); sys.stdout.flush()
""")


def _kill_at(root: Path, stage: str, *, prior: bool) -> None:
    code = CHILD.format(repo=str(REPO), root=str(root), stage=stage, prior=prior)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line == "READY", (line, proc.stderr.read() if proc.poll() is not None else "")
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        assert proc.returncode == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.is_file()}


@pytest.mark.parametrize("prior", [False, True])
@pytest.mark.parametrize("stage", ["after_raw", "after_journal"])
def test_kill9_between_raw_and_commit_refused_after_restart_never_repaired(tmp_path, stage, prior):
    _kill_at(tmp_path, stage, prior=prior)
    victim = [p for p in tmp_path.iterdir() if p.name.endswith(".json") and "victim" not in p.name]
    assert victim, "raw receipt must be on disk at kill time"
    before = _snapshot(tmp_path)

    # 1. verifier refuses the root (orphan raw or uncommitted intent), never returns entries
    with pytest.raises(ms.MLBSourceError, match="ORPHAN"):
        ms.verify_receipt_journal(tmp_path, verifier_now=LATER)
    # 2. a restarted recorder refuses to write on top of the orphan
    with patch.object(ms, "_trusted_now", return_value=NOW):
        with pytest.raises(ms.MLBSourceError, match="ORPHAN"):
            ms.MLBSourceCapture(tmp_path).record(url="https://example.test/next", raw=b"{}",
                                                 fetch_started_at=NOW, received_at=NOW)
    # 3. anchored admission refuses (admission is OFF anyway; must not reach the journal)
    out = ms.admit_anchored_receipt(tmp_path, "0" * 64, tsa_bundle=None, event_cutoff=LATER,
                                    verifier_now=LATER)
    assert out["admitted"] is False
    # 4. never repaired or backfilled: every byte on disk is unchanged
    assert _snapshot(tmp_path) == before
    with pytest.raises(ms.MLBSourceError, match="ORPHAN"):
        ms.verify_receipt_journal(tmp_path, verifier_now=LATER)


def test_unkilled_child_completes_and_verifies(tmp_path):
    code = CHILD.format(repo=str(REPO), root=str(tmp_path), stage="none", prior=True)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "FINISHED" in out.stdout, out.stderr
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=LATER)) == 2


def test_hand_planted_orphan_raw_refused(tmp_path):
    with patch.object(ms, "_trusted_now", return_value=NOW):
        ms.MLBSourceCapture(tmp_path).record(url="https://example.test/a", raw=b"{}",
                                             fetch_started_at=NOW, received_at=NOW)
    (tmp_path / ("0002_x_" + "a" * 64 + ".json")).write_bytes(b'{"x":1}')
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_ORPHAN_UNJOURNALED"):
        ms.verify_receipt_journal(tmp_path, verifier_now=LATER)


# ---------------------------- exactly one writer ----------------------------

def _calls(tree: ast.AST) -> dict[str, set[str]]:
    """function name -> names of write primitives it calls."""
    out: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hits = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
                    for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and isinstance(n.func, (ast.Name, ast.Attribute))}
            hits &= WRITE_PRIMITIVES
            if hits:
                out[fn.name] = hits
    return out


def test_exactly_one_receipt_writer_in_mlb_source():
    tree = ast.parse((SRC / "mlb_source.py").read_text(encoding="utf-8"))
    callers = _calls(tree)
    # _append_line_fsync is a thin wrapper over the primitive; the ONLY real writer is the
    # intent-journaled _append_receipt_locked.
    assert set(callers) == {"_append_line_fsync", "_append_receipt_locked"}, callers
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert "_receipt_writer_lock" not in names, "#2221 writer lock must be removed"
    record_src = ast.get_source_segment((SRC / "mlb_source.py").read_text(encoding="utf-8"),
                                        next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                                             and n.name == "record"))
    assert "_append_receipt_locked" in record_src


def test_no_other_module_writes_receipt_journal_or_imports_write_primitives():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "mlb_source.py":
            continue
        text = path.read_text(encoding="utf-8")
        if any(p in text for p in WRITE_PRIMITIVES):
            offenders.append(f"{path.relative_to(REPO)}:primitive")
        if "receipt_journal.jsonl" in text or "receipt_journal.intent.jsonl" in text:
            offenders.append(f"{path.relative_to(REPO)}:journal-name")
    assert offenders == [], offenders


def test_admit_anchored_receipt_is_read_only():
    tree = ast.parse((SRC / "mlb_source.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "admit_anchored_receipt")
    assert not _calls(fn)
