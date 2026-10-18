import os, json
from pathlib import Path
from unittest.mock import patch
import pytest
import sportsedge.mlb_source as ms
from tests.test_mlb_receipt_boundary_interruptions_20261014 import _run_injection, _snapshot, T0

def _target(fd):
    try:
        p = os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return "?"
    if p.endswith(ms.RECEIPT_INTENT_JOURNAL_NAME): return "intent"
    if p.endswith(ms.RECEIPT_JOURNAL_NAME): return "journal"
    if os.path.isdir(p): return "dir"
    return "other:" + p

@pytest.mark.parametrize("victim", ["journal", "intent", "dir"])
def test_each_target_failure_refuses(tmp_path, victim):
    root = _run_injection(tmp_path, "before_fsync", 9)
    before = _snapshot(root)
    real = os.fsync; hit = []
    def f(fd):
        t = _target(fd)
        if t == victim:
            hit.append(t); raise OSError("injected")
        return real(fd)
    with patch.object(os, "fsync", f):
        with pytest.raises(ms.MLBSourceError, match="RECEIPT_RECOVERY_SYNC_FAILED"):
            ms.verify_receipt_journal(root, verifier_now=T0)
        with patch.object(ms, "_trusted_now", lambda: T0):
            with pytest.raises(ms.MLBSourceError, match="RECEIPT_RECOVERY_SYNC_FAILED"):
                ms.MLBSourceCapture(root)
        r = ms.admit_anchored_receipt(root, "0"*64, tsa_bundle=None, event_cutoff=T0, verifier_now=T0)
        assert r["admitted"] is False
    assert hit, victim
    after = _snapshot(root)
    assert after == before
    intent = after.get(ms.RECEIPT_INTENT_JOURNAL_NAME, b"")
    assert intent.count(b"COMMIT") == before.get(ms.RECEIPT_INTENT_JOURNAL_NAME, b"").count(b"COMMIT")

def test_success_syncs_all_three(tmp_path):
    root = _run_injection(tmp_path, "before_fsync", 9)
    real = os.fsync; seen = []
    def f(fd):
        seen.append(_target(fd)); return real(fd)
    with patch.object(os, "fsync", f):
        ms.verify_receipt_journal(root, verifier_now=T0)
    assert {"journal", "intent", "dir"} <= set(seen)

@pytest.mark.parametrize("fsync_fails", [False, True])
def test_journal_only_root_refused(tmp_path, fsync_fails):
    root = _run_injection(tmp_path, "before_fsync", 9)
    (root / ms.RECEIPT_INTENT_JOURNAL_NAME).unlink()
    before = _snapshot(root)
    kw = {"side_effect": OSError("injected")} if fsync_fails else {"new": os.fsync}
    with patch.object(os, "fsync", **kw):
        with pytest.raises(ms.MLBSourceError, match="RECEIPT_INTENT_JOURNAL_MISSING"):
            ms.verify_receipt_journal(root, verifier_now=T0)
        with patch.object(ms, "_trusted_now", lambda: T0):
            with pytest.raises(ms.MLBSourceError, match="RECEIPT_INTENT_JOURNAL_MISSING"):
                ms.MLBSourceCapture(root)
        entries_sha = json.loads((root / ms.RECEIPT_JOURNAL_NAME).read_text().splitlines()[0])["record_sha256"]
        r = ms.admit_anchored_receipt(root, entries_sha, tsa_bundle=None, event_cutoff=T0, verifier_now=T0)
        assert r["admitted"] is False
    assert _snapshot(root) == before
    assert not (root / ms.RECEIPT_INTENT_JOURNAL_NAME).exists()


def test_admit_refuses_journal_only_even_if_gate_admits(tmp_path):
    root = _run_injection(tmp_path, "before_fsync", 9)
    (root / ms.RECEIPT_INTENT_JOURNAL_NAME).unlink()
    before = _snapshot(root)
    class D:
        admitted = True; reason = "admitted"; gen_time = None
    rec = json.loads((root / ms.RECEIPT_JOURNAL_NAME).read_text().splitlines()[0])["record_sha256"]
    with patch.object(ms._anchor_gate, "anchored_admission", lambda *a, **k: D()):
        r = ms.admit_anchored_receipt(root, rec, tsa_bundle=object(), event_cutoff=T0, verifier_now=T0)
    assert r["admitted"] is False and "RECEIPT_INTENT_JOURNAL_MISSING" in r["reason"]
    assert _snapshot(root) == before


@pytest.mark.parametrize("victim", ["journal", "intent", "dir"])
def test_admit_refuses_per_target_failure_even_if_gate_admits(tmp_path, victim):
    root = _run_injection(tmp_path, "before_fsync", 9)
    before = _snapshot(root)
    class D:
        admitted = True; reason = "admitted"; gen_time = None
    rec = json.loads((root / ms.RECEIPT_JOURNAL_NAME).read_text().splitlines()[0])["record_sha256"]
    real = os.fsync
    def f(fd):
        if _target(fd) == victim:
            raise OSError("injected")
        return real(fd)
    with patch.object(ms._anchor_gate, "anchored_admission", lambda *a, **k: D()), patch.object(os, "fsync", f):
        r = ms.admit_anchored_receipt(root, rec, tsa_bundle=object(), event_cutoff=T0, verifier_now=T0)
    assert r["admitted"] is False and "RECEIPT_RECOVERY_SYNC_FAILED" in r["reason"]
    assert _snapshot(root) == before
