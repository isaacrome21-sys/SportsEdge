"""Regression tests for the receipt-first safeguard audit (#2086).

The owner's integration audit reproduced three defects in the first
version of the safeguard; each test here reproduces his scenario
against the repaired code:

  1. INPUT INTEGRITY (TOCTOU): the wrapper receipted the input, then
     handed the pipeline the operator's ORIGINAL mutable file — the
     receipt preserved -163 while the runner saw -250 after a
     mutation in between. The pipeline must consume the immutable
     receipt snapshot, hash-verified immediately before the run.
  2. FALSE SUCCESS: a successful-looking CAPTURED verdict produced
     an ARCHIVED outcome even when no record existed. ARCHIVED now
     requires locating the record in the archive and verifying its
     existence, provenance input-hash, and game/market identity.
  3. CRASH RECOVERY: a receipt stuck at PENDING_EVALUATION could be
     auto-replayed by resubmission. It must instead report
     RECONCILIATION_REQUIRED; an explicit reconcile inspects the
     archive and records ARCHIVED when a verified record exists;
     only then may an operator explicitly request a fresh run.
     Recovery-state correction (owner, issue #2086): when
     reconciliation finds NO record, the outcome is INDETERMINATE,
     not REFUSED — the record's absence is established, but whether
     the interrupted runner started, crashed, or refused is not
     knowable, and REFUSED is reserved for established refusals.

Plus the durability/concurrency requirements from the same audit:
fsync on receipt/snapshot/outcome writes, and outcome appends that
cannot interleave partial lines across processes.

Round 3 (owner's audit of the round-2 export, issue #2086): the
exception rollback cannot run after abrupt process termination,
and newline termination alone is not a commit boundary — a writer
can die after the newline but before the outcome is durable. The
journal is now two-phase (entry line -> fsync -> ACK line bound
to the entry's SHA-256 -> fsync; committed only with its ACK),
with three recovery cases: exception rollback, torn-tail
truncation, and complete-but-unacknowledged entries (preserved,
reported, resolved to INDETERMINATE, reconciled by promotion on
verified ground truth or supersession). The wrapper also
persists the v1 verdict's elo_schedule_provenance on ARCHIVED
outcomes (null + note when absent). Covered by the last section
of this file, including two process-death regressions that
SIGKILL a subprocess mid-append.

Round 2 (owner's independent audit of the corrected export, issue
#2086) reproduced two further regressions, covered by the final
section of this file:

  4. PARTIAL OUTCOME WRITE: a short/failed write to outcomes.jsonl
     left a corrupt partial line and every subsequent read failed.
     A failed append must roll the journal back to its pre-append
     offset; the journal must never retain a partial line.
  5. MISSING FIXTURE IDENTITY: a wrong-game record could be
     accepted as ARCHIVED when identity fields were missing or
     unverifiable, because verification only compared the fields
     that were present. Verification now fails closed: EVERY
     identity element (provenance input-hash, fixture_id, market,
     selection, line) must be present and matching on both sides.

Round 4 (owner's independent reproduction against the round-3
export, issue #2086): the journal exposed an outcome before
commitment. read_outcomes() read the journal WITHOUT the
writer's lock, so during an append that failed at the ACK fsync
(OUTCOME_WRITE_FAILED, then rollback to the append-start
offset), a concurrent reader in the window between the ACK
becoming visible and the rollback completing reported the
doomed outcome as committed (owner's sequence: committed = 1,
append failed, committed = 0). The fix is coordinated reader
locking, not another ACK layer: every journal reader takes the
receipts lock shared (LOCK_SH), and the writer holds it
exclusively across the ENTIRE append protocol — recovery,
entry write + fsync, ACK write + fsync, and rollback — so a
reader observes only durable-or-absent states. Covered by the
final section of this file, alongside the SIGKILL tests.

Round 5 (owner's independent test of the round-4 export,
issue #2086): the concurrent-reader rollback test now PASSES —
that blocker is closed — but the post-ACK crash window remains:
a writer SIGKILLed AFTER the ACK line's write() completes but
BEFORE the ACK fsync leaves entry+ACK in the page cache;
process death releases the lock, and the next reader reported
the entry as COMMITTED with zero recovery fsync calls —
durability was never established, contradicting the round-4
"durable-or-absent" contract. The fix is a recovery-durability
step under the coordinated lock, not another ACK layer: every
scan that would expose committed entries first fsyncs the
journal (and its directory) under the lock, making surviving
bytes durable as of recovery. If that fsync fails, the
trailing ACK-backed unit — the only unit that can lack a
completed writer-side fsync, since appends are serialized and
a later ACK implies a later writer's completed phase-1 fsync
of the whole prefix — is treated exactly like an
unacknowledged entry, never as committed. Covered by the
final section of this file: the exact SIGKILL window, with
fsync ordering instrumented, and the recovery-fsync-failure
variant.
"""
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from sportsedge.backtest import capture_receipt as rcpt
from sportsedge.backtest import forward_capture as fc

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SCRIPT = REPO_ROOT / "scripts" / "capture_strict_mlb_record_v2.py"


def _load_v2():
    spec = importlib.util.spec_from_file_location(
        "capture_strict_mlb_record_v2_audit", V2_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = _load_v2()

KICK = "2026-10-13T00:00:00Z"


def make_input(**overrides):
    spec = {
        "schema": "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1",
        "away": "Cleveland Guardians", "home": "Tampa Bay Rays",
        "kickoff_utc": KICK, "series_id": "2026-ALCS-CLE-TB",
        "market": "ML", "selection": "HOME", "line": "ML",
        "book": "draftkings",
        "selection_american": -163,
        "selection_captured_at_utc": "2026-10-12T23:33:09Z",
        "opposite_american": 145,
        "opposite_captured_at_utc": "2026-10-12T23:33:09Z",
        "quote_source": "browser-captured DraftKings event page (test)",
    }
    spec.update(overrides)
    return spec


def write_input(tmp_path, spec=None, name="capture_input.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec or make_input(), indent=2),
                    encoding="utf-8")
    return path


def write_record(archive_dir, consumed_path, *, provenance_sha256=None,
                 name="fixture__ML__HOME.json"):
    """Write an archived record modeled on the real v1 output."""
    spec = json.loads(Path(consumed_path).read_text(encoding="utf-8"))
    if provenance_sha256 is None:
        provenance_sha256 = hashlib.sha256(
            Path(consumed_path).read_bytes()).hexdigest()
    captures = Path(archive_dir) / "captures"
    captures.mkdir(parents=True, exist_ok=True)
    record = {
        "fixture_id": fc.fixture_id_for(spec["away"], spec["home"],
                                        spec["kickoff_utc"]),
        "market": str(spec["market"]).upper(),
        "selection": str(spec["selection"]).upper(),
        # The real v1 record always carries a line ("ML" for a
        # moneyline, a float otherwise) — modeled faithfully here
        # because verification now requires it (audit #2086 round 2).
        "line": "ML" if str(spec["market"]).upper() == "ML"
                else float(spec["line"]),
        "capture_provenance": {"input_sha256": provenance_sha256},
    }
    path = captures / name
    path.write_text(json.dumps(record, indent=2, sort_keys=True),
                    encoding="utf-8")
    return path, record


def captured_verdict(record_path, record):
    return {"exit_code": 0,
            "stdout": json.dumps(
                {"status": "CAPTURED", "file": str(record_path),
                 "fixture_id": record["fixture_id"],
                 "candidate_p": 0.63, "existing_p": 0.55,
                 "model_source_sha": "b" * 40,
                 "compliance_warnings": []},
                indent=2, sort_keys=True),
            "stderr": ""}


# ------------------------------------------- 1. input integrity (TOCTOU)

def test_runner_consumes_snapshot_not_mutable_original(tmp_path):
    """Owner's reproduction: receipt says -163; the original file is
    mutated to -250 in the window between receipt and run. The runner
    must still price the receipted bytes (-163)."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    seen = {}

    def racing_runner(input_path, archive_dir):
        # Simulate the race: mutate the operator's original file
        # AFTER receipting, before reading what we were handed.
        mutated = make_input(selection_american=-250)
        input_file.write_text(json.dumps(mutated, indent=2),
                              encoding="utf-8")
        seen["path_given"] = Path(input_path)
        consumed = json.loads(
            Path(input_path).read_text(encoding="utf-8"))
        return {"exit_code": 1,
                "stdout": json.dumps(
                    {"status": "CAPTURE_REFUSED",
                     "reason": "SAW_PRICE:%s" %
                               consumed["selection_american"]}),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=racing_runner)
    assert report["status"] == "REFUSED"
    # Priced the receipted bytes, not the mutated original.
    assert report["refusal_reason"] == "SAW_PRICE:-163"
    # The runner was handed the snapshot, never the original path.
    snap = rcpt.snapshot_path(archive, report["receipt_id"])
    assert seen["path_given"] == snap
    assert seen["path_given"] != input_file
    # The snapshot is byte-identical to the receipted input, and the
    # outcome records that the run consumed it.
    receipt = rcpt.receipt_status(archive, report["receipt_id"])
    assert hashlib.sha256(snap.read_bytes()).hexdigest() == \
        receipt["receipt"]["input_sha256"]
    assert receipt["receipt"]["input"]["selection_american"] == -163
    outcome = receipt["outcome"]
    assert outcome["input_source"] == "RECEIPT_SNAPSHOT"
    assert outcome["input_snapshot_path"] == str(snap)
    assert outcome["input_snapshot_sha256"] == \
        receipt["receipt"]["input_sha256"]


def test_tampered_snapshot_refuses_before_running(tmp_path):
    """If the snapshot on disk no longer matches the receipt hash,
    the run refuses (INPUT_SNAPSHOT_HASH_MISMATCH); the pipeline is
    never invoked against unreceipted bytes."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    calls = []

    def crash_runner(input_path, archive_dir):
        calls.append(1)
        raise KeyboardInterrupt  # process died mid-run: PENDING receipt

    with pytest.raises(KeyboardInterrupt):
        v2.capture_with_receipt(input_file, archive,
                                runner=crash_runner)
    # Reconcile (no record in the archive) so an outcome is on record
    # and an explicit rerun becomes permissible. The interrupted
    # run's outcome is unknowable, so reconciliation records
    # INDETERMINATE, not REFUSED.
    report = v2.capture_with_receipt(input_file, archive,
                                     runner=crash_runner, reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    # Tamper with the snapshot, then explicitly request a fresh run.
    snap = rcpt.snapshot_path(archive, report["receipt_id"])
    snap.write_bytes(b'{"selection_american": -250}')
    calls.clear()

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner, rerun=True)
    assert report["status"] == "REFUSED"
    assert report["refusal_reason"].startswith(
        "INPUT_SNAPSHOT_HASH_MISMATCH")
    assert calls == []  # pipeline never ran


# ------------------------------------------------------- 2. false success

def test_fake_success_without_any_record_is_refused(tmp_path):
    """exit 0 + a CAPTURED-looking verdict, but nothing was written
    to the archive: the outcome must be REFUSED, never ARCHIVED."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def lying_runner(input_path, archive_dir):
        ghost = Path(archive_dir) / "captures" / "ghost.json"
        return {"exit_code": 0,
                "stdout": json.dumps(
                    {"status": "CAPTURED", "file": str(ghost),
                     "fixture_id": "mlb:2026-10-12:CLE:TB",
                     "candidate_p": 0.63, "existing_p": 0.55,
                     "model_source_sha": "b" * 40,
                     "compliance_warnings": []}, indent=2),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=lying_runner)
    assert report["status"] == "REFUSED"
    assert report["refusal_reason"] == \
        "ARCHIVED_RECORD_VERIFICATION_FAILED"
    assert report["record_path"] is None
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "REFUSED"
    assert status["outcome"]["claimed_record_path"].endswith(
        "ghost.json")
    failures = status["outcome"]["verification"]["failures"]
    assert any(f["check_failed"] == "RECORD_NOT_FOUND"
               for f in failures)


def test_record_with_mismatched_provenance_is_refused(tmp_path):
    """A record exists and the verdict points at it, but its stored
    provenance input-hash is not the receipt's: REFUSED."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def wrong_provenance_runner(input_path, archive_dir):
        record_path, record = write_record(
            archive_dir, input_path, provenance_sha256="0" * 64)
        return captured_verdict(record_path, record)

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=wrong_provenance_runner)
    assert report["status"] == "REFUSED"
    assert report["refusal_reason"] == \
        "ARCHIVED_RECORD_VERIFICATION_FAILED"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    failures = status["outcome"]["verification"]["failures"]
    assert any(f["check_failed"] == "PROVENANCE_INPUT_HASH_MISMATCH"
               for f in failures)


def test_verified_record_is_archived_with_verified_path(tmp_path):
    """A stub that writes a correct record (exists, provenance hash
    equals the receipt's, identity matches) yields ARCHIVED naming
    the verified path."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def honest_runner(input_path, archive_dir):
        record_path, record = write_record(archive_dir, input_path)
        return captured_verdict(record_path, record)

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=honest_runner)
    assert report["status"] == "ARCHIVED"
    assert Path(report["record_path"]).is_file()
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "ARCHIVED"
    assert status["outcome"]["record_verified"] is True
    assert status["outcome"]["record_path"] == report["record_path"]


# ----------------------------------------------------- 3. crash recovery

def _crash_pending_receipt(tmp_path):
    """Run once with a runner that dies mid-flight (KeyboardInterrupt
    propagates like a killed process): receipt written, pipeline ran
    exactly once, no outcome appended."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    calls = []

    def crash_runner(input_path, archive_dir):
        calls.append(1)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        v2.capture_with_receipt(input_file, archive,
                                runner=crash_runner)
    assert len(calls) == 1
    receipts = rcpt.read_receipts(archive)
    assert len(receipts) == 1
    receipt_id = receipts[0][1]["receipt_id"]
    assert rcpt.receipt_status(archive, receipt_id)["status"] == \
        "PENDING_EVALUATION"
    return archive, input_file, receipt_id, calls


def test_pending_duplicate_requires_reconciliation_no_rerun(tmp_path):
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner)
    assert report["status"] == "RECONCILIATION_REQUIRED"
    assert report["pipeline_rerun"] is False
    assert len(calls) == 1  # still exactly one pipeline run, ever
    assert rcpt.read_outcomes(archive) == []  # nothing appended either


def test_reconcile_not_found_records_indeterminate_unknown(tmp_path):
    """Crash-matrix case (b): crash DURING the run. Reconciliation
    finds no record, so the outcome is INDETERMINATE — absence is the
    only established fact; the run may have crashed anywhere, and an
    unknowable refusal must not be recorded as an established one.
    (Pre-correction this asserted REFUSED; updated to the owner's
    INDETERMINATE semantics, issue #2086.)"""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    assert report["refusal_reason"] == \
        "NO_ARCHIVED_RECORD_FOUND_ON_RECONCILIATION"
    assert len(calls) == 1  # reconciliation never runs the pipeline
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["refusal_reason"] is None  # nothing was refused
    outcome = status["outcome"]
    assert outcome["outcome"] == "INDETERMINATE"
    assert outcome["reconciled"] is True
    assert outcome["original_outcome_unknown"] is True
    assert "unknown" in outcome["note"]


def test_reconcile_found_records_archived(tmp_path):
    """Crash-matrix case (c): crash AFTER the record was written but
    BEFORE the outcome was appended. Reconciliation finds and
    verifies the record -> ARCHIVED."""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)
    # The crashed run HAD in fact archived a record before dying.
    snap = rcpt.snapshot_path(archive, receipt_id)
    record_path, _record = write_record(archive, snap)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "ARCHIVED"
    assert report["record_path"] == str(record_path)
    assert len(calls) == 1
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["outcome"]["reconciled"] is True
    assert status["status"] == "ARCHIVED"


def test_explicit_rerun_permitted_only_after_reconciliation(tmp_path):
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)

    def refusing_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1,
                "stdout": json.dumps(
                    {"status": "CAPTURE_REFUSED",
                     "reason": "STILL_REFUSED"}),
                "stderr": ""}

    # --rerun while still PENDING: reconciliation is required first;
    # the rerun flag does not bypass it.
    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner, rerun=True)
    assert report["status"] == "RECONCILIATION_REQUIRED"
    assert len(calls) == 1
    # Reconcile (no record -> INDETERMINATE), then the explicit
    # rerun is permitted.
    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner, rerun=True)
    assert report["status"] == "REFUSED"
    assert report["refusal_reason"] == "STILL_REFUSED"
    assert len(calls) == 2
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["outcome"]["operator_rerun"] is True


def test_reconcile_crash_before_runner_start_is_indeterminate(
        tmp_path):
    """Crash-matrix case (a): the process died after receipting but
    BEFORE the runner ever started — the on-disk state is a bare
    PENDING receipt. Reconciliation finds no record -> INDETERMINATE,
    and the pipeline is never invoked by reconciliation itself."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    raw = input_file.read_bytes()
    spec = json.loads(raw.decode("utf-8"))
    _path, receipt, _dup = rcpt.write_receipt(archive, raw, spec)
    receipt_id = receipt["receipt_id"]
    assert rcpt.receipt_status(archive, receipt_id)["status"] == \
        "PENDING_EVALUATION"
    calls = []

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    assert calls == []  # runner never started, even for reconcile
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["outcome"]["original_outcome_unknown"] is True


def test_reconcile_unknowable_refusal_is_indeterminate(tmp_path,
                                                       monkeypatch):
    """Crash-matrix case (d): the runner DID refuse, but the process
    died before the outcome was appended. After the fact the refusal
    is unknowable — reconciliation must record INDETERMINATE, never
    REFUSED, even though a refusal is what actually happened."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def refusing_runner(input_path, archive_dir):
        return {"exit_code": 1,
                "stdout": json.dumps(
                    {"status": "CAPTURE_REFUSED",
                     "reason": "A_REAL_REFUSAL_THAT_WAS_NEVER_RECORDED"}),
                "stderr": ""}

    real_append = rcpt.append_outcome

    def dying_append(archive_dir, outcome):
        raise KeyboardInterrupt  # killed between verdict and append

    monkeypatch.setattr(rcpt, "append_outcome", dying_append)
    with pytest.raises(KeyboardInterrupt):
        v2.capture_with_receipt(input_file, archive,
                                runner=refusing_runner)
    monkeypatch.setattr(rcpt, "append_outcome", real_append)
    receipts = rcpt.read_receipts(archive)
    receipt_id = receipts[0][1]["receipt_id"]
    assert rcpt.receipt_status(archive, receipt_id)["status"] == \
        "PENDING_EVALUATION"
    assert rcpt.read_outcomes(archive) == []

    def counting_runner(input_path, archive_dir):
        raise AssertionError("reconciliation must not run the runner")

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["status"] != "REFUSED"
    assert status["refusal_reason"] is None
    assert status["outcome"]["reason"] == \
        "NO_ARCHIVED_RECORD_FOUND_ON_RECONCILIATION"


def test_duplicate_against_indeterminate_receipt_never_reruns(
        tmp_path):
    """Crash-matrix case (e): once a receipt is INDETERMINATE, a
    plain duplicate submission reports the recorded state and runs
    nothing — a fresh attempt requires the explicit --rerun
    submission, never an automatic replay."""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["recorded_status"] == "INDETERMINATE"
    outcomes_before = len(rcpt.read_outcomes(archive))

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner)
    assert report["status"] == "RECEIPT_DUPLICATE"
    assert report["recorded_status"] == "INDETERMINATE"
    assert report["pipeline_rerun"] is False
    assert report["record_path"] is None
    assert len(calls) == 1  # still only the original crashed run
    assert len(rcpt.read_outcomes(archive)) == outcomes_before


# ------------------------------------------- concurrency and durability

def _append_worker(archive_dir, proc_idx, count):
    for i in range(count):
        rcpt.append_outcome(archive_dir, {
            "receipt_id": "rcpt_concurrency",
            "outcome": "REFUSED",
            "reason": "proc%d-line%d" % (proc_idx, i)})


def test_concurrent_outcome_appends_never_interleave(tmp_path):
    archive = tmp_path / "archive"
    procs, per_proc = 4, 25
    ctx = multiprocessing.get_context("fork")
    workers = [ctx.Process(target=_append_worker,
                           args=(str(archive), p, per_proc))
               for p in range(procs)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
        assert w.exitcode == 0
    # Two-phase commit (round 3): each append is an entry line plus
    # its ACK line, and the pairs never interleave — every entry is
    # immediately followed by the ACK bound to its exact bytes.
    raw = rcpt.outcomes_path(archive).read_bytes().splitlines()
    assert len(raw) == 2 * procs * per_proc
    reasons = set()
    for i in range(0, len(raw), 2):
        entry = json.loads(raw[i])  # every line intact, parseable
        ack = json.loads(raw[i + 1])
        assert ack == {"ack": hashlib.sha256(raw[i]).hexdigest()}
        reasons.add(entry["reason"])
    assert len(reasons) == procs * per_proc
    assert len(rcpt.read_outcomes(archive)) == procs * per_proc


def test_fsync_on_receipt_snapshot_and_outcome_writes(tmp_path,
                                                      monkeypatch):
    real_fsync = os.fsync
    calls = []

    def counting_fsync(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    archive = tmp_path / "archive"
    spec = make_input()
    raw = json.dumps(spec).encode("utf-8")

    calls.clear()
    _path, receipt, _dup = rcpt.write_receipt(archive, raw, spec)
    receipt_fsyncs = len(calls)
    assert receipt_fsyncs >= 2  # receipt file + receipts directory

    calls.clear()
    rcpt.ensure_input_snapshot(archive, receipt["receipt_id"], raw,
                               receipt["input_sha256"])
    assert len(calls) >= 2  # snapshot file + snapshots directory

    calls.clear()
    rcpt.append_outcome(archive, {
        "receipt_id": receipt["receipt_id"], "outcome": "REFUSED",
        "reason": "DURABILITY_PROBE"})
    assert len(calls) >= 2  # outcomes file + receipts directory


# ----------------------- round 2, regression 4: journal integrity

def test_short_write_then_raise_rolls_back_journal(tmp_path,
                                                   monkeypatch):
    """Owner's reproduction: os.write emits half the payload, then
    raises. The journal must afterwards parse fully, prior entries
    intact, and a subsequent append must succeed — a failed write
    must not poison the journal."""
    archive = tmp_path / "archive"
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_journal", "outcome": "REFUSED",
        "reason": "SEEDED_ENTRY"})
    journal = rcpt.outcomes_path(archive)
    seeded_size = journal.stat().st_size

    real_write = os.write
    calls = {"n": 0}

    def flaky_write(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_write(fd, data[:len(data) // 2])
        raise OSError("simulated write failure")

    monkeypatch.setattr(os, "write", flaky_write)
    with pytest.raises(rcpt.ReceiptError):
        rcpt.append_outcome(archive, {
            "receipt_id": "rcpt_journal", "outcome": "ARCHIVED",
            "reason": "THIS_MUST_NOT_SURVIVE"})
    monkeypatch.undo()

    # The partial line was rolled back: size and content unchanged.
    assert journal.stat().st_size == seeded_size
    entries = rcpt.read_outcomes(archive)  # parses fully
    assert [e["reason"] for e in entries] == ["SEEDED_ENTRY"]
    # And the journal still accepts appends afterwards.
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_journal", "outcome": "REFUSED",
        "reason": "AFTER_ROLLBACK"})
    entries = rcpt.read_outcomes(archive)
    assert [e["reason"] for e in entries] == [
        "SEEDED_ENTRY", "AFTER_ROLLBACK"]


def test_short_write_counts_complete_via_write_loop(tmp_path,
                                                    monkeypatch):
    """A writer that returns short counts (never raises) must still
    produce one complete committed outcome: an intact entry line
    followed by its ACK line (two-phase commit, round 3)."""
    archive = tmp_path / "archive"
    real_write = os.write

    def short_write(fd, data):
        return real_write(fd, bytes(data[:7]))

    monkeypatch.setattr(os, "write", short_write)
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_short_counts", "outcome": "REFUSED",
        "reason": "A_REASON_FAR_LONGER_THAN_SEVEN_BYTES"})
    monkeypatch.undo()
    entries = rcpt.read_outcomes(archive)
    assert len(entries) == 1
    assert entries[0]["reason"] == \
        "A_REASON_FAR_LONGER_THAN_SEVEN_BYTES"
    raw = rcpt.outcomes_path(archive).read_bytes()
    lines = raw.splitlines()
    assert raw.endswith(b"\n") and len(lines) == 2
    assert json.loads(lines[1]) == {
        "ack": hashlib.sha256(lines[0]).hexdigest()}


def test_torn_trailing_fragment_is_uncommitted_not_fatal(tmp_path):
    """Round 3 redefines this round-2 scenario (the owner's SIGKILL
    reproduction): a partial trailing line — no terminating
    newline — is a TORN TAIL: uncommitted bytes, never parsed as
    an outcome, but NOT fatal to the read either. The committed
    entries come back, and the tail is reported distinctly by
    size (the round-2 behavior — raising OUTCOME_JOURNAL_MALFORMED_LINE
    for the tail — made a killed writer poison every read, which
    is precisely what crash recovery must not do)."""
    archive = tmp_path / "archive"
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_malformed", "outcome": "REFUSED",
        "reason": "GOOD_LINE"})
    journal = rcpt.outcomes_path(archive)
    fragment = b'{"outcome": "ARCHIVED", "receipt_id": "rc'
    with open(journal, "ab") as handle:
        handle.write(fragment)
    entries = rcpt.read_outcomes(archive)  # no raise
    assert [e["reason"] for e in entries] == ["GOOD_LINE"]
    journal_status = rcpt.outcome_journal_status(archive)
    assert journal_status["entry_count"] == 1
    assert journal_status["torn_tail_bytes"] == len(fragment)


def test_committed_region_corruption_still_raises_distinctly(
        tmp_path):
    """The malformed-line error is reserved for corruption INSIDE
    the committed region: a complete line that fails to parse
    while parseable journal lines follow it. That is real damage,
    not an interrupted write — reads raise the distinct error
    naming the line (never a bare JSON error), and appends refuse
    rather than truncating or writing past it."""
    archive = tmp_path / "archive"
    journal = rcpt.outcomes_path(archive)
    journal.parent.mkdir(parents=True, exist_ok=True)

    def pair(reason):
        line = json.dumps(
            {"outcome": "REFUSED", "receipt_id": "rcpt_corrupt",
             "reason": reason}, sort_keys=True).encode("utf-8")
        ack = json.dumps(
            {"ack": hashlib.sha256(line).hexdigest()},
            sort_keys=True).encode("utf-8")
        return line + b"\n" + ack + b"\n"

    journal.write_bytes(pair("FIRST") + b'{"outcome": "BROKEN", \n'
                        + pair("SECOND"))
    with pytest.raises(rcpt.ReceiptError) as excinfo:
        rcpt.read_outcomes(archive)
    assert "OUTCOME_JOURNAL_MALFORMED_LINE:3" in str(excinfo.value)
    assert not isinstance(excinfo.value, json.JSONDecodeError)
    before = journal.read_bytes()
    with pytest.raises(rcpt.ReceiptError):
        rcpt.append_outcome(archive, {
            "receipt_id": "rcpt_corrupt", "outcome": "REFUSED",
            "reason": "MUST_NOT_APPEND_PAST_CORRUPTION"})
    assert journal.read_bytes() == before  # nothing truncated/written


# ------------------- round 2, regression 5: fail-closed identity

def _captured_verdict(record_path, fixture_id):
    return {"exit_code": 0,
            "stdout": json.dumps(
                {"status": "CAPTURED", "file": str(record_path),
                 "fixture_id": fixture_id,
                 "candidate_p": 0.63, "existing_p": 0.55,
                 "model_source_sha": "b" * 40,
                 "compliance_warnings": []}, indent=2),
            "stderr": ""}


def _custom_record_runner(record_builder):
    """Runner that writes a record built by ``record_builder``
    (spec, snapshot_path) -> dict and claims success."""
    def run(input_path, archive_dir):
        spec = json.loads(Path(input_path).read_text(
            encoding="utf-8"))
        record = record_builder(spec, input_path)
        captures = Path(archive_dir) / "captures"
        captures.mkdir(parents=True, exist_ok=True)
        path = captures / "fixture__ML__HOME.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True),
                        encoding="utf-8")
        return _captured_verdict(path, record.get("fixture_id"))
    return run


def _valid_record(spec, snapshot_path, **overrides):
    record = {
        "fixture_id": fc.fixture_id_for(spec["away"], spec["home"],
                                        spec["kickoff_utc"]),
        "market": str(spec["market"]).upper(),
        "selection": str(spec["selection"]).upper(),
        "line": "ML" if str(spec["market"]).upper() == "ML"
                else float(spec["line"]),
        "capture_provenance": {
            "input_sha256": hashlib.sha256(
                Path(snapshot_path).read_bytes()).hexdigest()},
    }
    record.update(overrides)
    return record


def _failures(report, archive):
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "REFUSED"
    assert status["outcome"]["reason"] == \
        "ARCHIVED_RECORD_VERIFICATION_FAILED"
    return status["outcome"]["verification"]["failures"]


def test_wrong_game_record_with_valid_provenance_is_refused(
        tmp_path):
    """(a) The record's provenance hash matches the receipt, but the
    record is for a DIFFERENT game: REFUSED, naming fixture_id."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    wrong_fixture = fc.fixture_id_for(
        "New York Yankees", "Boston Red Sox", KICK)

    def builder(spec, snap):
        return _valid_record(spec, snap, fixture_id=wrong_fixture)

    report = v2.capture_with_receipt(
        input_file, archive, runner=_custom_record_runner(builder))
    assert report["status"] == "REFUSED"
    assert report["record_path"] is None
    failures = _failures(report, archive)
    assert any(f["check_failed"] == "FIXTURE_ID_MISMATCH"
               for f in failures)


def test_record_with_missing_identity_elements_is_refused(
        tmp_path):
    """(b) A record missing (or nulling) any identity element —
    fixture_id, market, selection, line, provenance input-hash —
    fails closed, naming the specific element."""
    mutations = [
        ("fixture_id", "IDENTITY_MISSING:fixture_id"),
        ("market", "IDENTITY_MISSING:market"),
        ("selection", "IDENTITY_MISSING:selection"),
        ("line", "IDENTITY_MISSING:line"),
    ]
    for idx, (field, expected) in enumerate(mutations):
        for variant in ("deleted", "null"):
            archive = tmp_path / ("archive%d_%s" % (idx, variant))
            input_file = write_input(tmp_path)

            def builder(spec, snap, field=field, variant=variant):
                record = _valid_record(spec, snap)
                if variant == "deleted":
                    del record[field]
                else:
                    record[field] = None
                return record

            report = v2.capture_with_receipt(
                input_file, archive,
                runner=_custom_record_runner(builder))
            assert report["status"] == "REFUSED", (field, variant)
            failures = _failures(report, archive)
            assert any(f["check_failed"] == expected
                       for f in failures), (field, variant, failures)

    # Provenance envelope without the input hash at all.
    archive = tmp_path / "archive_provenance"
    input_file = write_input(tmp_path)

    def no_hash_builder(spec, snap):
        return _valid_record(spec, snap, capture_provenance={})

    report = v2.capture_with_receipt(
        input_file, archive,
        runner=_custom_record_runner(no_hash_builder))
    assert report["status"] == "REFUSED"
    failures = _failures(report, archive)
    assert any(f["check_failed"] ==
               "IDENTITY_MISSING:provenance.input_sha256"
               for f in failures)


def test_underivable_expected_identity_fails_closed(tmp_path):
    """(b, expected side) The input cannot yield a fixture identity
    (no kickoff to derive it from). Even a record whose provenance
    matches the receipt must be REFUSED: verification fails before
    any candidate is read, naming the unverifiable element."""
    archive = tmp_path / "archive"
    spec = make_input()
    del spec["kickoff_utc"]
    input_file = write_input(tmp_path, spec=spec)

    def run(input_path, archive_dir):
        record = {
            "fixture_id": "mlb:2026-10-12:CLE:TB",
            "market": "ML", "selection": "HOME", "line": "ML",
            "capture_provenance": {
                "input_sha256": hashlib.sha256(
                    Path(input_path).read_bytes()).hexdigest()},
        }
        captures = Path(archive_dir) / "captures"
        captures.mkdir(parents=True, exist_ok=True)
        path = captures / "fixture__ML__HOME.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True),
                        encoding="utf-8")
        return _captured_verdict(path, record["fixture_id"])

    report = v2.capture_with_receipt(input_file, archive, runner=run)
    assert report["status"] == "REFUSED"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    verification = status["outcome"]["verification"]
    assert verification["candidates_checked"] == 0
    assert any(f["check_failed"] ==
               "EXPECTED_IDENTITY_UNVERIFIABLE:fixture_id"
               for f in verification["failures"])


def test_verify_with_underivable_fixture_never_returns_wrong_game(
        tmp_path):
    """The owner's unit-level reproduction of regression 5: verify
    is asked to check a record while the fixture identity is
    unverifiable (None). The old code skipped the fixture check
    entirely and returned the wrong-game record as verified; the
    fixed code fails closed before reading any candidate."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    raw = input_file.read_bytes()
    spec = json.loads(raw.decode("utf-8"))
    _path, receipt, _dup = rcpt.write_receipt(archive, raw, spec)
    snap, _created = rcpt.ensure_input_snapshot(
        archive, receipt["receipt_id"], raw, receipt["input_sha256"])
    wrong = _valid_record(
        spec, snap,
        fixture_id=fc.fixture_id_for("New York Yankees",
                                      "Boston Red Sox", KICK))
    captures = archive / "captures"
    captures.mkdir(parents=True, exist_ok=True)
    (captures / "wrong_game.json").write_text(
        json.dumps(wrong, indent=2, sort_keys=True),
        encoding="utf-8")
    found, details = rcpt.verify_archived_record(
        archive, input_sha256=receipt["input_sha256"],
        fixture_id=None, market="ML", selection="HOME", line="ML")
    assert found is None
    assert details["candidates_checked"] == 0
    assert any(f["check_failed"] ==
               "EXPECTED_IDENTITY_UNVERIFIABLE:fixture_id"
               for f in details["failures"])


def test_line_identity_checked_for_line_markets(tmp_path):
    """Line is an identity element where applicable: a SPREAD
    record for the right game at the WRONG line is refused; the
    same record at the input's line is the positive control."""
    spread = make_input(market="SPREAD", selection="HOME",
                        line=-1.5, selection_american=-110)

    archive = tmp_path / "archive_wrong_line"
    input_file = write_input(tmp_path, spec=spread)

    def wrong_line_builder(spec, snap):
        return _valid_record(spec, snap, line=1.5)

    report = v2.capture_with_receipt(
        input_file, archive,
        runner=_custom_record_runner(wrong_line_builder))
    assert report["status"] == "REFUSED"
    failures = _failures(report, archive)
    assert any(f["check_failed"] == "LINE_MISMATCH"
               for f in failures)

    archive = tmp_path / "archive_right_line"
    report = v2.capture_with_receipt(
        input_file, archive,
        runner=_custom_record_runner(_valid_record))
    assert report["status"] == "ARCHIVED"
    assert Path(report["record_path"]).is_file()


# ----------------- round 3: journal crash recovery (ACK commit model)
#
# The owner's round-3 correction: try/except rollback cannot run
# after abrupt process termination, and a newline alone is not a
# commit boundary — a process can die AFTER writing the newline
# but BEFORE the outcome is durable. Appends are therefore
# two-phase (entry line -> fsync -> ACK line bound to the entry
# line's SHA-256 -> fsync) and an entry is committed only with
# its ACK present. The two subprocess tests below reproduce
# process death itself (SIGKILL), not a simulation of it.

_DIE_WRITING_CHILD = (
    "import os, signal, sys\n"
    "fd = os.open(sys.argv[1],\n"
    "             os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)\n"
    "os.write(fd, sys.argv[2].encode('utf-8'))\n"
    "os.kill(os.getpid(), signal.SIGKILL)\n"
)


def _die_writing(tmp_path, journal, payload):
    """Append ``payload`` (str) to the journal from a subprocess
    that SIGKILLs itself immediately after the write — no fsync,
    no ACK, no cleanup, no rollback: abrupt process death inside
    the append window, exactly the owner's reproduction."""
    script = tmp_path / "die_writing_child.py"
    script.write_text(_DIE_WRITING_CHILD, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(journal), payload],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == -signal.SIGKILL


def _seed_receipt(tmp_path, archive):
    input_file = write_input(tmp_path)
    raw = input_file.read_bytes()
    spec = json.loads(raw.decode("utf-8"))
    _path, receipt, _dup = rcpt.write_receipt(archive, raw, spec)
    return input_file, receipt["receipt_id"]


def test_append_writes_entry_plus_bound_ack(tmp_path):
    """The commit unit on disk: an entry line immediately followed
    by its ACK line, the ACK bound to the entry line's SHA-256."""
    archive = tmp_path / "archive"
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_ack", "outcome": "REFUSED",
        "reason": "ACK_BOUND"})
    lines = rcpt.outcomes_path(archive).read_bytes().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["reason"] == "ACK_BOUND"
    assert json.loads(lines[1]) == {
        "ack": hashlib.sha256(lines[0]).hexdigest()}
    status = rcpt.outcome_journal_status(archive)
    assert status["entry_count"] == 1
    assert status["unacknowledged_entries"] == 0
    assert status["torn_tail_bytes"] == 0


def test_orphan_ack_is_committed_region_corruption(tmp_path):
    """An ACK bound to no entry anywhere before it cannot be
    produced by any writer path (torn-tail truncation cuts a
    suffix; it can never orphan an ACK) — it is corruption inside
    the committed region and reads raise the distinct error."""
    archive = tmp_path / "archive"
    journal = rcpt.outcomes_path(archive)
    journal.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"outcome": "REFUSED",
                       "receipt_id": "rcpt_orphan",
                       "reason": "REAL_ENTRY"},
                      sort_keys=True).encode("utf-8")
    journal.write_bytes(
        line + b"\n"
        + json.dumps({"ack": "0" * 64}).encode("utf-8") + b"\n")
    with pytest.raises(rcpt.ReceiptError) as excinfo:
        rcpt.read_outcomes(archive)
    assert "OUTCOME_JOURNAL_MALFORMED_LINE:2" in str(excinfo.value)


def test_process_death_torn_tail_recovers(tmp_path):
    """OWNER'S PROCESS-DEATH REGRESSION (torn tail): a subprocess
    writes a PARTIAL outcome line (no newline) and is SIGKILLed
    before any fsync/ACK/rollback could run. The fragment must
    not poison the journal: committed entries stay readable, the
    tail is reported by size, and the next append truncates the
    fragment and lands cleanly."""
    archive = tmp_path / "archive"
    input_file, receipt_id = _seed_receipt(tmp_path, archive)
    for reason in ("SEEDED_1", "SEEDED_2"):
        rcpt.append_outcome(archive, {
            "receipt_id": receipt_id, "outcome": "REFUSED",
            "reason": reason})
    journal = rcpt.outcomes_path(archive)
    fragment = '{"outcome": "ARCHIVED", "receipt_id": "%s", "reco' \
        % receipt_id
    _die_writing(tmp_path, journal, fragment)

    entries = rcpt.read_outcomes(archive)  # no raise, committed only
    assert [e["reason"] for e in entries] == ["SEEDED_1", "SEEDED_2"]
    journal_status = rcpt.outcome_journal_status(archive)
    assert journal_status["entry_count"] == 2
    assert journal_status["torn_tail_bytes"] == len(
        fragment.encode("utf-8"))
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "REFUSED"  # latest committed outcome
    assert status["torn_tail_bytes"] == len(fragment.encode("utf-8"))

    rcpt.append_outcome(archive, {
        "receipt_id": receipt_id, "outcome": "REFUSED",
        "reason": "AFTER_DEATH"})
    entries = rcpt.read_outcomes(archive)
    assert [e["reason"] for e in entries] == [
        "SEEDED_1", "SEEDED_2", "AFTER_DEATH"]
    assert entries[-1]["journal_recovered_torn_bytes"] == len(
        fragment.encode("utf-8"))
    # The final journal parses end-to-end as entry/ACK pairs.
    raw_lines = journal.read_bytes().splitlines()
    assert len(raw_lines) == 6
    for i in range(0, len(raw_lines), 2):
        assert json.loads(raw_lines[i + 1]) == {
            "ack": hashlib.sha256(raw_lines[i]).hexdigest()}
    assert rcpt.outcome_journal_status(archive)[
        "torn_tail_bytes"] == 0


def test_torn_tail_then_reconcile_recovers_and_records(tmp_path):
    """A torn tail in front of a PENDING receipt: reconciliation's
    append performs the recovery (the INDETERMINATE entry records
    the recovered byte count) and the journal ends fully valid."""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)
    journal = rcpt.outcomes_path(archive)
    fragment = b'{"outcome": "REFUSED", "receipt_id": "rcpt_torn", "re'
    with open(journal, "ab") as handle:
        handle.write(fragment)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "INDETERMINATE"
    assert len(calls) == 1  # reconciliation never runs the pipeline
    entries = rcpt.read_outcomes(archive)
    assert len(entries) == 1
    assert entries[0]["outcome"] == "INDETERMINATE"
    assert entries[0]["journal_recovered_torn_bytes"] == len(fragment)
    assert rcpt.outcome_journal_status(archive)[
        "torn_tail_bytes"] == 0


def _unacknowledged_entry(tmp_path, archive, entry):
    """Kill a subprocess that wrote ONE complete entry line
    (newline included) but died BEFORE fsync/ACK — the
    complete-but-unacknowledged crash window."""
    journal = rcpt.outcomes_path(archive)
    journal.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True)
    _die_writing(tmp_path, journal, line + "\n")
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def test_process_death_unacknowledged_archived_promoted(tmp_path):
    """OWNER'S CRASH-WINDOW REGRESSION (promotion path): a writer
    dies after the entry line's newline but before fsync/ACK. The
    entry is complete-but-unacknowledged: NOT counted as an
    outcome, NOT silently dropped — the receipt resolves to
    INDETERMINATE. Reconciliation then verifies ground truth (the
    archived record exists and verifies), appends the entry's
    ACK (promotion) plus a confirming ARCHIVED outcome."""
    archive = tmp_path / "archive"
    input_file, receipt_id = _seed_receipt(tmp_path, archive)
    record_path, record = write_record(archive, input_file)
    ghost = {"outcome": "ARCHIVED", "receipt_id": receipt_id,
             "record_path": str(record_path),
             "fixture_id": record["fixture_id"],
             "record_verified": True,
             "input_source": "RECEIPT_SNAPSHOT"}
    ghost_sha = _unacknowledged_entry(tmp_path, archive, ghost)

    # Reported as unacknowledged, not counted, not dropped.
    assert rcpt.read_outcomes(archive) == []
    journal_status = rcpt.outcome_journal_status(archive)
    assert journal_status["entry_count"] == 0
    assert journal_status["unacknowledged_entries"] == 1
    assert journal_status["torn_tail_bytes"] == 0
    unacked = rcpt.unacknowledged_outcomes(archive)
    assert [u["sha256"] for u in unacked] == [ghost_sha]
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["outcome"] is None
    assert status["unacknowledged_outcome"]["outcome"] == "ARCHIVED"
    assert status["unacknowledged_entry_sha256"] == ghost_sha

    calls = []

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert calls == []  # reconciliation never runs the pipeline
    assert report["status"] == "RECONCILED"
    assert report["recorded_status"] == "ARCHIVED"
    assert report["record_path"] == str(record_path)
    entries = rcpt.read_outcomes(archive)
    assert len(entries) == 2
    assert entries[0] == ghost  # the promoted entry itself, in order
    confirming = entries[1]
    assert confirming["outcome"] == "ARCHIVED"
    assert confirming["reconciled"] is True
    assert confirming["confirms_unacknowledged_entry_sha256"] == \
        ghost_sha
    assert rcpt.outcome_journal_status(archive)[
        "unacknowledged_entries"] == 0
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "ARCHIVED"
    assert status["outcome"] == confirming


def test_process_death_unacknowledged_archived_superseded(tmp_path):
    """Crash window, supersede path: the unacknowledged entry
    claims ARCHIVED but NO record verifies on disk. The claim was
    never durably established, so reconciliation supersedes it
    with a committed INDETERMINATE; the ghost entry stays in the
    journal, preserved and reported, never counted."""
    archive = tmp_path / "archive"
    input_file, receipt_id = _seed_receipt(tmp_path, archive)
    ghost = {"outcome": "ARCHIVED", "receipt_id": receipt_id,
             "record_path": str(archive / "captures" / "ghost.json"),
             "record_verified": True}
    ghost_sha = _unacknowledged_entry(tmp_path, archive, ghost)
    assert rcpt.receipt_status(archive, receipt_id)["status"] == \
        "INDETERMINATE"

    def counting_runner(input_path, archive_dir):
        raise AssertionError("reconciliation must not run the runner")

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["recorded_status"] == "INDETERMINATE"
    entries = rcpt.read_outcomes(archive)
    assert len(entries) == 1  # only the superseding outcome counts
    superseding = entries[0]
    assert superseding["outcome"] == "INDETERMINATE"
    assert superseding["reason"] == \
        "UNACKNOWLEDGED_OUTCOME_NOT_DURABLY_ESTABLISHED"
    assert superseding[
        "supersedes_unacknowledged_entry_sha256"] == ghost_sha
    assert superseding["unacknowledged_outcome_type"] == "ARCHIVED"
    assert "verification" in superseding
    # The ghost is preserved and still reported as unacknowledged.
    assert [u["sha256"] for u in
            rcpt.unacknowledged_outcomes(archive)] == [ghost_sha]
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["outcome"] == superseding


def test_process_death_unacknowledged_refusal_superseded(tmp_path):
    """Crash window, REFUSED-type entry: a refusal whose ACK never
    landed was never durably established, so it is NOT an
    established refusal — the receipt resolves to INDETERMINATE
    and reconciliation supersedes the entry with a committed
    INDETERMINATE outcome."""
    archive = tmp_path / "archive"
    input_file, receipt_id = _seed_receipt(tmp_path, archive)
    ghost = {"outcome": "REFUSED", "receipt_id": receipt_id,
             "reason": "A_REFUSAL_THAT_NEVER_BECAME_DURABLE"}
    ghost_sha = _unacknowledged_entry(tmp_path, archive, ghost)
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["status"] != "REFUSED"
    assert status["refusal_reason"] is None
    assert rcpt.read_outcomes(archive) == []

    def counting_runner(input_path, archive_dir):
        raise AssertionError("reconciliation must not run the runner")

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["recorded_status"] == "INDETERMINATE"
    entries = rcpt.read_outcomes(archive)
    assert len(entries) == 1
    assert entries[0]["outcome"] == "INDETERMINATE"
    assert entries[0][
        "supersedes_unacknowledged_entry_sha256"] == ghost_sha
    assert entries[0]["unacknowledged_outcome_type"] == "REFUSED"


# ----------------- round 3: provenance persistence (wrapper, part B)

_ELO_PROVENANCE = {
    "source_observed_at_utc": "2026-10-12T23:20:00Z",
    "source_origin": "HTTP",
    "consumer_read_at_utc": "2026-10-12T23:20:04Z",
    "schedule_content_sha256": "a" * 64,
    "schedule_hash_basis": "CANONICAL_PARSED_CONTENT",
    "pit_provenance_status": "PIT_PROVENANCE_ESTABLISHED",
}


def _provenance_runner(input_path, archive_dir):
    record_path, record = write_record(archive_dir, input_path)
    verdict = captured_verdict(record_path, record)
    payload = json.loads(verdict["stdout"])
    payload["elo_schedule_provenance"] = _ELO_PROVENANCE
    verdict["stdout"] = json.dumps(payload, indent=2, sort_keys=True)
    return verdict


def test_archived_outcome_persists_elo_schedule_provenance(tmp_path):
    """The ARCHIVED outcome entry carries the v1 verdict's
    elo_schedule_provenance object VERBATIM (the frozen record
    format cannot carry it; the outcome entry is where the
    point-in-time Elo evidence survives)."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    report = v2.capture_with_receipt(input_file, archive,
                                     runner=_provenance_runner)
    assert report["status"] == "ARCHIVED"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["outcome"]["elo_schedule_provenance"] == \
        _ELO_PROVENANCE
    assert "provenance_note" not in status["outcome"]


def test_archived_outcome_without_provenance_records_null_note(
        tmp_path):
    """A verdict with no elo_schedule_provenance: the ARCHIVED
    outcome records it as null WITH a provenance_note — absence
    is stated, values are never reconstructed."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def honest_runner(input_path, archive_dir):
        record_path, record = write_record(archive_dir, input_path)
        return captured_verdict(record_path, record)

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=honest_runner)
    assert report["status"] == "ARCHIVED"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["outcome"]["elo_schedule_provenance"] is None
    assert "no elo_schedule_provenance" in \
        status["outcome"]["provenance_note"]


def test_refused_flows_do_not_gain_provenance_fields(tmp_path):
    """REFUSED outcomes — established refusals and crashes alike —
    are unaffected: no provenance key, no note is attached."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def refusing_runner(input_path, archive_dir):
        return {"exit_code": 1,
                "stdout": json.dumps(
                    {"status": "CAPTURE_REFUSED",
                     "reason": "PLAIN_REFUSAL"}),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner)
    assert report["status"] == "REFUSED"
    outcome = rcpt.receipt_status(
        archive, report["receipt_id"])["outcome"]
    assert "elo_schedule_provenance" not in outcome
    assert "provenance_note" not in outcome

    archive2 = tmp_path / "archive2"
    input_file2 = write_input(tmp_path, name="capture_input2.json")

    def crashing_runner(input_path, archive_dir):
        return {"exit_code": 1, "stdout": "",
                "stderr": "Traceback (most recent call last):\n"
                          "RuntimeError: BOOM"}

    report2 = v2.capture_with_receipt(input_file2, archive2,
                                      runner=crashing_runner)
    assert report2["status"] == "REFUSED"
    outcome2 = rcpt.receipt_status(
        archive2, report2["receipt_id"])["outcome"]
    assert "elo_schedule_provenance" not in outcome2
    assert "provenance_note" not in outcome2


def test_reconciled_archived_records_null_provenance_with_note(
        tmp_path):
    """An ARCHIVED outcome produced by reconciliation (which ran
    no pipeline) records elo_schedule_provenance as null with a
    note — the key is present on every ARCHIVED outcome, and its
    absence of content is explained rather than silent."""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)
    snap = rcpt.snapshot_path(archive, receipt_id)
    record_path, _record = write_record(archive, snap)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["recorded_status"] == "ARCHIVED"
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["outcome"]["elo_schedule_provenance"] is None
    assert "no pipeline" in status["outcome"]["provenance_note"]


# ----------------- round 4: coordinated reader locking
#
# The owner's round-4 reproduction (issue #2086): read_outcomes()
# accepted the visible ACK without acquiring the writer's lock.
# During an append that fails at the ACK fsync, the entry line
# and the ACK line are both already written to the journal file;
# the writer then rolls back to the append-start offset. A reader
# polling in that window reported the doomed outcome as committed
# (owner's sequence: committed = 1 -> OUTCOME_WRITE_FAILED ->
# rollback -> committed = 0). The fix: readers take the receipts
# lock SHARED (LOCK_SH); the writer holds it EXCLUSIVELY across
# the entire append protocol, rollback included. No reader can
# observe an intermediate append state — only durable-or-absent.


def test_concurrent_reader_never_observes_rolled_back_outcome(
        tmp_path):
    """OWNER'S ROUND-4 REGRESSION: an append whose ACK fsync is
    made to fail (deterministically injected) while a reader
    thread polls read_outcomes(). The fsync stub holds the
    failure window open — entry line and ACK line both already
    in the file, rollback not yet run — until the reader has had
    ample opportunity to poll inside it. NO reader snapshot may
    ever contain the doomed outcome, every snapshot must equal a
    durable-or-absent state (here: the pre-append committed set),
    and the final committed set must equal the pre-append set.
    Against the pre-fix code (readers took no lock) the reader
    observes the ghost inside the window and this test fails."""
    archive = tmp_path / "archive"
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_baseline", "outcome": "REFUSED",
        "reason": "BASELINE_COMMITTED"})
    baseline_ids = {"rcpt_baseline"}

    real_fsync = os.fsync
    state = {"armed": False, "fsync_calls": 0}
    window_open = threading.Event()
    polls = {"count": 0}
    snapshots = []
    stop = threading.Event()

    def flaky_fsync(fd):
        if not state["armed"]:
            return real_fsync(fd)
        state["fsync_calls"] += 1
        if state["fsync_calls"] == 2:
            # The doomed append's ACK fsync. Both lines of the
            # commit unit are already written; only durability
            # (and then the rollback) is outstanding. Hold the
            # window open until the reader has polled repeatedly
            # — post-fix it cannot complete a poll here at all
            # (it is parked on the shared lock), so the bounded
            # wait simply elapses — then fail the fsync.
            window_open.set()
            start_polls = polls["count"]
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if polls["count"] - start_polls >= 3:
                    break
                time.sleep(0.005)
            raise OSError("injected ACK fsync failure")
        return real_fsync(fd)

    def reader():
        while not stop.is_set():
            entries = rcpt.read_outcomes(archive)
            snapshots.append(
                {entry.get("receipt_id") for entry in entries})
            polls["count"] += 1
            time.sleep(0.001)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        # The reader is live and seeing only the baseline state.
        deadline = time.monotonic() + 5.0
        while polls["count"] < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert polls["count"] >= 3
        assert all(snap == baseline_ids for snap in snapshots)

        state["armed"] = True
        os.fsync = flaky_fsync
        try:
            with pytest.raises(rcpt.ReceiptError) as excinfo:
                rcpt.append_outcome(archive, {
                    "receipt_id": "rcpt_doomed",
                    "outcome": "REFUSED",
                    "reason": "DOOMED_BY_ACK_FSYNC_FAILURE"})
        finally:
            os.fsync = real_fsync
            state["armed"] = False
        assert "OUTCOME_WRITE_FAILED" in str(excinfo.value)
        assert window_open.is_set()
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()

    # No snapshot ever contained the doomed outcome; every
    # snapshot is a durable-or-absent state (the baseline set).
    assert snapshots
    assert all("rcpt_doomed" not in snap for snap in snapshots)
    assert all(snap == baseline_ids for snap in snapshots)
    # The final committed set equals the pre-append set.
    final = rcpt.read_outcomes(archive)
    assert {e["receipt_id"] for e in final} == baseline_ids
    assert rcpt.outcome_journal_status(archive)["entry_count"] == 1


def test_committed_append_visible_once_writer_releases_lock(
        tmp_path):
    """Round 4, converse: coordination hides only UNCOMMITTED
    states. A successfully committed append — ACK fsynced under
    the writer's lock hold — IS visible to a reader that starts
    after append_outcome returns (lock released): committed
    state is durable and reported, never hidden by the read
    lock."""
    archive = tmp_path / "archive"
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_first", "outcome": "REFUSED",
        "reason": "FIRST_COMMITTED"})
    entries = rcpt.read_outcomes(archive)
    assert [e["receipt_id"] for e in entries] == ["rcpt_first"]
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_second", "outcome": "REFUSED",
        "reason": "SECOND_COMMITTED"})
    assert [e["receipt_id"] for e in rcpt.read_outcomes(archive)] \
        == ["rcpt_first", "rcpt_second"]
    assert rcpt.outcome_journal_status(archive)["entry_count"] == 2
    assert rcpt.latest_outcomes(archive)["rcpt_second"]["reason"] \
        == "SECOND_COMMITTED"


def test_reconcile_reads_under_its_own_lock_without_deadlock(
        tmp_path):
    """Round 4 deadlock guard: reconciliation holds the
    exclusive lock while deriving state from the journal. It
    must read through the unlocked internal helpers — if it
    called the public (shared-locking) readers it would
    self-deadlock on flock's non-re-entrancy across separate
    opens. This exercises that path end to end: a PENDING
    receipt reconciles to INDETERMINATE without hanging."""
    archive, input_file, receipt_id, calls = \
        _crash_pending_receipt(tmp_path)

    def counting_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1, "stdout": "", "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=counting_runner,
                                     reconcile=True)
    assert report["recorded_status"] == "INDETERMINATE"
    assert rcpt.receipt_status(archive, receipt_id)["status"] == \
        "INDETERMINATE"


# ----------------- round 5: recovery durability (post-ACK crash window)
#
# The owner's round-5 reproduction (issue #2086): the round-4
# rollback-visibility blocker is closed (his concurrent-reader
# test passes), but a writer SIGKILLed AFTER the ACK line's
# write() completes and BEFORE the ACK fsync still defeats the
# durability contract: process death releases the lock, the
# complete entry+ACK unit survives in the page cache, and the
# next reader — locking correctly — reported the entry as
# COMMITTED with ZERO recovery fsync calls. Its durability was
# never established by anyone. The fix: under the coordinated
# lock, the scan runs a recovery-durability step (fsync the
# journal + its directory) BEFORE exposing surviving ACK-backed
# entries; if that fsync cannot establish durability, the
# trailing ACK-backed unit is reported through the unacknowledged
# path (INDETERMINATE flow), never as committed. No additional
# ACK layer.


def _unfsynced_committed_unit(tmp_path, archive, entry):
    """Kill a subprocess that wrote a COMPLETE commit unit — one
    entry line plus its bound ACK line, in protocol order — and
    died BEFORE any fsync: the exact round-5 window. The child
    performs raw writes only, so no fsync of the unit ever
    completed; the unit survives in the page cache looking
    byte-identical to a durable commit."""
    journal = rcpt.outcomes_path(archive)
    journal.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True)
    ack = json.dumps(
        {"ack": hashlib.sha256(line.encode("utf-8")).hexdigest()},
        sort_keys=True)
    _die_writing(tmp_path, journal, line + "\n" + ack + "\n")
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _post_ack_death_journal(tmp_path, archive):
    """A journal holding: one genuinely durable committed unit
    (appended through the real protocol, writer fsyncs
    completed), followed by a complete entry+ACK unit whose
    writer was SIGKILLed after the ACK write, before the ACK
    fsync — plus the receipt the ghost unit names."""
    input_file, receipt_id = _seed_receipt(tmp_path, archive)
    rcpt.append_outcome(archive, {
        "receipt_id": "rcpt_prior", "outcome": "REFUSED",
        "reason": "PRIOR_DURABLE"})
    ghost = {"outcome": "ARCHIVED", "receipt_id": receipt_id,
             "record_path": str(archive / "captures" / "ghost.json"),
             "record_verified": True,
             "input_source": "RECEIPT_SNAPSHOT"}
    ghost_sha = _unfsynced_committed_unit(tmp_path, archive, ghost)
    return receipt_id, ghost, ghost_sha


def test_process_death_after_ack_write_recovery_fsync_precedes_exposure(
        tmp_path, monkeypatch):
    """OWNER'S ROUND-5 REGRESSION (the exact SIGKILL window): a
    subprocess writes entry + ACK in protocol order and is
    SIGKILLed before ANY fsync (asserted: returncode -SIGKILL,
    the complete unit present in the journal, no fsync ever
    completed for it). The parent then reads under the lock
    with fsync instrumented: the read must itself perform the
    recovery fsync, and only after that fsync succeeds may the
    surviving unit be exposed as committed — alongside the
    genuinely durable prior unit. Against the pre-fix code the
    reader exposes the unit with zero fsync calls (the owner's
    result) and the fsync assertion fails."""
    archive = tmp_path / "archive"
    receipt_id, ghost, ghost_sha = _post_ack_death_journal(
        tmp_path, archive)
    journal = rcpt.outcomes_path(archive)
    raw = journal.read_bytes()
    # The complete unit survived the writer's death, unfsynced:
    # prior entry+ACK pair, then the ghost entry+ACK pair.
    assert raw.count(b"\n") == 4
    assert json.loads(raw.splitlines()[3]) == {"ack": ghost_sha}

    real_fsync = os.fsync
    fsync_calls = []

    def recording_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    entries = rcpt.read_outcomes(archive)
    # The recovery fsync ran inside this read, BEFORE exposure:
    # the ghost unit is only present in the result because the
    # read first made its surviving bytes durable.
    assert fsync_calls, \
        "entries exposed with no recovery fsync (pre-fix behavior)"
    assert [e["receipt_id"] for e in entries] == [
        "rcpt_prior", receipt_id]
    assert entries[0]["reason"] == "PRIOR_DURABLE"
    assert entries[1] == ghost
    assert rcpt.outcome_journal_status(archive)[
        "entry_count"] == 2
    assert rcpt.unacknowledged_outcomes(archive) == []


def test_process_death_after_ack_write_failed_recovery_demotes(
        tmp_path, monkeypatch):
    """Round 5, failure branch: same SIGKILL window, but the
    recovery fsync is made to fail (injected OSError). The
    trailing ACK-backed unit's durability cannot be established,
    so it is treated EXACTLY like an unacknowledged entry:
    preserved, reported via unacknowledged_outcomes, never
    committed; its receipt resolves to INDETERMINATE. The
    earlier unit — whose writer completed the protocol — remains
    exposable. And nothing is destroyed: once a later scan's
    recovery fsync succeeds, the same surviving bytes are
    exposed as committed (demotion is a per-scan durability
    verdict, not an edit)."""
    archive = tmp_path / "archive"
    receipt_id, ghost, ghost_sha = _post_ack_death_journal(
        tmp_path, archive)
    journal_size = rcpt.outcomes_path(archive).stat().st_size

    def failing_fsync(fd):
        raise OSError("injected recovery fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    entries = rcpt.read_outcomes(archive)
    assert [e["receipt_id"] for e in entries] == ["rcpt_prior"]
    unacked = rcpt.unacknowledged_outcomes(archive)
    assert [u["sha256"] for u in unacked] == [ghost_sha]
    assert unacked[0]["entry"] == ghost
    journal_status = rcpt.outcome_journal_status(archive)
    assert journal_status["entry_count"] == 1
    assert journal_status["unacknowledged_entries"] == 1
    status = rcpt.receipt_status(archive, receipt_id)
    assert status["status"] == "INDETERMINATE"
    assert status["outcome"] is None
    assert status["unacknowledged_entry_sha256"] == ghost_sha
    monkeypatch.undo()

    # The journal was not truncated or rewritten while its
    # durability was unproven, and recovery on a later scan
    # exposes the identical unit as committed.
    assert rcpt.outcomes_path(archive).stat().st_size == \
        journal_size
    entries = rcpt.read_outcomes(archive)
    assert [e["receipt_id"] for e in entries] == [
        "rcpt_prior", receipt_id]
    assert entries[1] == ghost
