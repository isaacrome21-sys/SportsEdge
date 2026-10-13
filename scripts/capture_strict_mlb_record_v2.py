#!/usr/bin/env python3
"""Receipt-first strict MLB forward capture.

A wrapper around the frozen v1 capture CLI
(``scripts/capture_strict_mlb_record.py``) that preserves the perishable
evidence BEFORE any model or Elo dependency runs:

1. The capture input is written verbatim into the archive's receipts
   area (``<archive-dir>/receipts/rcpt_<sha>.json``, write-once) with
   status ``PENDING_EVALUATION`` — see
   ``sportsedge/backtest/capture_receipt.py``.
2. The receipted bytes are copied to an immutable, content-addressed
   snapshot (``receipts/snapshots/``), and the v1 capture pipeline
   runs **unchanged** (subprocess, same frozen checkout) against the
   SNAPSHOT — never the operator's mutable original file, whose hash
   is re-verified immediately before the run (audit #2086).
3. The pipeline's verdict is appended to
   ``<archive-dir>/receipts/outcomes.jsonl``: ``ARCHIVED`` with the
   record path, or ``REFUSED`` with the verbatim refusal reason — or,
   when the pipeline crashes without producing a verdict (e.g. the
   October 12, 2026 ``BACKTEST_SOURCE_UNAVAILABLE`` traceback), the
   failure class and the crash's final line. An ``ARCHIVED`` outcome
   is appended only after the archived record is located in the
   archive and verified (exists; provenance input-hash equals the
   receipt's; game/market identity matches) — a successful-looking
   pipeline response alone never suffices. The ``ARCHIVED`` outcome
   also persists the verdict's ``elo_schedule_provenance`` object
   verbatim (the frozen record format cannot carry it); when the
   verdict carried none, the outcome records it as null with a
   ``provenance_note`` instead of reconstructed values.

A receipt left at ``PENDING_EVALUATION`` by a crashed run is never
auto-replayed: resubmission reports ``RECONCILIATION_REQUIRED``.
``--reconcile`` inspects the archive: a verified record records
``ARCHIVED``, but no record records ``INDETERMINATE`` — the record's
absence is established, while whether the interrupted runner started,
crashed, or refused is not knowable and is never recorded as an
established refusal. Only after an outcome is on record may an
operator request a fresh run with ``--rerun``.

Why: on 2026-10-12 the v1 CLI refused *after* the quotes were captured
(the Elo leg's full-season schedule fetch exceeded an 8 MB response
cap), so no evaluator record was archived and the timestamped quotes
survived only in a hand-filed raw-evidence JSON. Under this wrapper the
quotes are already an immutable receipt before the pipeline starts;
a refusal stays a refusal, but the evidence can never be lost with it.

A receipt marked REFUSED means the quotes were preserved and **no
evaluator record exists**, with the refusal established. A receipt
marked INDETERMINATE means the same about the record, but the
interrupted run's outcome is unknown rather than refused. The
receipt is not, and never becomes, an evaluator record.

Usage (identical operator flow to v1, different entry point):

    python scripts/capture_strict_mlb_record_v2.py \
        --input capture_cle_tb.json \
        --archive-dir archive/strict-forward-capture

Exit code mirrors the pipeline outcome: 0 when a record was archived,
1 when the capture was refused (including receipt duplicates whose
recorded outcome was a refusal).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.backtest import capture_receipt as rcpt
from sportsedge.backtest import forward_capture as fc

V1_SCRIPT = Path(__file__).resolve().parent / "capture_strict_mlb_record.py"
_STDERR_TAIL_LIMIT = 16384


def run_pipeline_subprocess(input_path, archive_dir):
    """Run the frozen v1 capture CLI unchanged; return its raw result."""
    proc = subprocess.run(
        [sys.executable, str(V1_SCRIPT),
         "--input", str(input_path),
         "--archive-dir", str(archive_dir)],
        capture_output=True, text=True)
    return {"exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or ""}


def _crash_fields(stderr):
    """Extract (failure_class, verbatim final line) from a traceback."""
    lines = [ln for ln in (stderr or "").splitlines() if ln.strip()]
    last = lines[-1].strip() if lines else ""
    failure_class = last.split(":", 1)[0].strip() if ":" in last else last
    return failure_class, last


def interpret_result(result):
    """Translate a pipeline run into receipt-outcome fields.

    The v1 CLI prints a JSON verdict on stdout: CAPTURED (exit 0) or
    CAPTURE_REFUSED with a verbatim reason (exit 1). Anything else —
    a traceback, an unrecognized payload — is a crash: the outcome is
    REFUSED with the failure class, never a guessed success.
    """
    stdout = (result.get("stdout") or "").strip()
    verdict = None
    if stdout:
        # The v1 CLI prints one JSON verdict: single-line on refusal,
        # pretty-printed on success. Try the whole payload, then the
        # final line.
        for candidate in (stdout, stdout.splitlines()[-1]):
            try:
                parsed = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                verdict = parsed
                break
    if verdict and verdict.get("status") == "CAPTURED" \
            and result.get("exit_code") == 0:
        fields = {
            "outcome": rcpt.STATUS_ARCHIVED,
            "record_path": verdict.get("file"),
            "fixture_id": verdict.get("fixture_id"),
            "candidate_p": verdict.get("candidate_p"),
            "existing_p": verdict.get("existing_p"),
            "model_source_sha": verdict.get("model_source_sha"),
            "compliance_warnings": verdict.get("compliance_warnings"),
            "pipeline_exit_code": result.get("exit_code"),
            # Persist the Elo schedule provenance the v1 CLI
            # reported on stdout (audit #2086, round 3): the FULL
            # object, verbatim. It is the point-in-time evidence
            # for the Elo leg's training schedule (source
            # observation time and origin, consumer-read time,
            # content hash, PIT provenance status) and the frozen
            # archived record cannot carry it, so the outcome entry
            # is where it survives.
            "elo_schedule_provenance": verdict.get(
                "elo_schedule_provenance"),
        }
        if fields["elo_schedule_provenance"] is None:
            # No provenance in the verdict: record null with a
            # note — never reconstruct or fabricate values.
            fields["provenance_note"] = (
                "the v1 pipeline verdict carried no "
                "elo_schedule_provenance object; recorded as null "
                "rather than reconstructed — schedule-provenance "
                "evidence is unavailable for this outcome")
        return fields
    if verdict and verdict.get("status") == "CAPTURE_REFUSED":
        return {
            "outcome": rcpt.STATUS_REFUSED,
            "reason": verdict.get("reason"),
            "pipeline_exit_code": result.get("exit_code"),
        }
    failure_class, last_line = _crash_fields(result.get("stderr"))
    stderr = result.get("stderr") or ""
    outcome = {
        "outcome": rcpt.STATUS_REFUSED,
        "reason": last_line,
        "failure_class": failure_class or "PIPELINE_NO_VERDICT",
        "crash": True,
        "pipeline_exit_code": result.get("exit_code"),
        "pipeline_stderr_tail": stderr[-_STDERR_TAIL_LIMIT:],
    }
    if len(stderr) > _STDERR_TAIL_LIMIT:
        outcome["pipeline_stderr_truncated"] = True
    return outcome


def _expected_identity(input_obj):
    """(fixture_id, market, selection, line) the record must match.

    Every element is None when it cannot be derived from the input;
    verification fails closed on any missing element (audit #2086,
    round 2), so an ARCHIVED claim whose identity is underivable
    from the input is refused, never waved through. The line is
    "ML" for a moneyline input and a float for SPREAD/TOTAL,
    matching the v1 record format exactly.
    """
    try:
        fixture_id = fc.fixture_id_for(input_obj.get("away"),
                                       input_obj.get("home"),
                                       input_obj.get("kickoff_utc"))
    except Exception:
        fixture_id = None
    market = str(input_obj.get("market") or "").upper()
    selection = str(input_obj.get("selection") or "").upper()
    raw_line = input_obj.get("line")
    if market == "ML":
        line = "ML" if str(raw_line or "").strip().upper() == "ML" \
            else None
    else:
        try:
            line = float(raw_line)
        except (TypeError, ValueError):
            line = None
    return fixture_id, market, selection, line


def _run_pipeline(receipt, input_obj, input_bytes, archive_dir, *,
                  runner, receipt_file, duplicate, rerun):
    """Snapshot -> verify -> run v1 against the snapshot -> verify the
    archived record -> append the outcome. The pipeline NEVER sees the
    operator's original (mutable) input path (audit #2086)."""
    receipt_id = receipt["receipt_id"]
    expected_sha = receipt["input_sha256"]
    try:
        snap_path, _created = rcpt.ensure_input_snapshot(
            archive_dir, receipt_id, input_bytes, expected_sha)
    except rcpt.ReceiptError as exc:
        outcome = {
            "outcome": rcpt.STATUS_REFUSED,
            "reason": str(exc),
            "failure_class": "ReceiptError",
            "receipt_id": receipt_id,
        }
        rcpt.append_outcome(archive_dir, outcome)
        return {"status": rcpt.STATUS_REFUSED,
                "receipt_id": receipt_id,
                "receipt_path": str(receipt_file),
                "receipt_duplicate": duplicate,
                "record_path": None,
                "refusal_reason": str(exc),
                "failure_class": "ReceiptError"}
    # Re-verify the snapshot's hash immediately before running, so a
    # mutation of anything on disk between receipt and run refuses
    # instead of pricing bytes that were never receipted.
    hash_ok, _actual = rcpt.verify_snapshot(
        archive_dir, receipt_id, expected_sha)
    if not hash_ok:
        reason = "INPUT_SNAPSHOT_HASH_MISMATCH"
        outcome = {"outcome": rcpt.STATUS_REFUSED, "reason": reason,
                   "failure_class": "ReceiptError",
                   "receipt_id": receipt_id}
        rcpt.append_outcome(archive_dir, outcome)
        return {"status": rcpt.STATUS_REFUSED,
                "receipt_id": receipt_id,
                "receipt_path": str(receipt_file),
                "receipt_duplicate": duplicate,
                "record_path": None,
                "refusal_reason": reason,
                "failure_class": "ReceiptError"}
    run = runner or run_pipeline_subprocess
    try:
        result = run(snap_path, archive_dir)
        outcome = interpret_result(result)
    except Exception as exc:  # the runner itself failed to execute
        outcome = {
            "outcome": rcpt.STATUS_REFUSED,
            "reason": str(exc),
            "failure_class": type(exc).__name__,
            "crash": True,
            "pipeline_exit_code": None,
        }
    outcome["input_source"] = "RECEIPT_SNAPSHOT"
    outcome["input_snapshot_path"] = str(snap_path)
    outcome["input_snapshot_sha256"] = expected_sha
    if rerun:
        outcome["operator_rerun"] = True
    if outcome["outcome"] == rcpt.STATUS_ARCHIVED:
        # Never trust the pipeline's verdict alone: locate the record
        # in the archive and verify existence + provenance + identity.
        fixture_id, market, selection, line = _expected_identity(
            input_obj)
        found, record_or_details = rcpt.verify_archived_record(
            archive_dir, input_sha256=expected_sha,
            fixture_id=fixture_id, market=market, selection=selection,
            line=line, candidate_path=outcome.get("record_path"))
        if found is not None:
            outcome["claimed_record_path"] = outcome.get("record_path")
            outcome["record_path"] = str(found)
            outcome["record_verified"] = True
        else:
            claimed = outcome.get("record_path")
            outcome["claimed_record_path"] = claimed
            outcome["record_path"] = None
            outcome["outcome"] = rcpt.STATUS_REFUSED
            outcome["reason"] = "ARCHIVED_RECORD_VERIFICATION_FAILED"
            outcome["verification"] = record_or_details
    outcome["receipt_id"] = receipt_id
    # Outcome appended — the receipt file is never edited.
    rcpt.append_outcome(archive_dir, outcome)
    report = {
        "status": outcome["outcome"],
        "receipt_id": receipt_id,
        "receipt_path": str(receipt_file),
        "receipt_duplicate": duplicate,
        "snapshot_path": str(snap_path),
        "record_path": outcome.get("record_path"),
        "refusal_reason": outcome.get("reason"),
        "failure_class": outcome.get("failure_class"),
    }
    return report


def capture_with_receipt(input_path, archive_dir, *, runner=None,
                         now=None, reconcile=False, rerun=False):
    """Receipt first, pipeline second, outcome appended last.

    ``runner(input_path, archive_dir) -> {exit_code, stdout, stderr}``
    is injectable for tests; the default runs the v1 CLI as a
    subprocess. The runner is always handed the immutable input
    SNAPSHOT inside the receipts area, never the operator's original
    path. Returns the auditor-facing report dict.

    Duplicate handling (audit #2086): a receipt with a recorded
    outcome is reported, never re-run (unless ``rerun=True`` — an
    explicit operator request after reconciliation). A receipt with
    NO outcome (a prior run died mid-flight) is never auto-replayed:
    the report is RECONCILIATION_REQUIRED unless ``reconcile=True``,
    which inspects the archive and records ARCHIVED (record found and
    verified) or INDETERMINATE (no record found; the interrupted
    run's outcome is unknown, not refused).
    """
    input_path = Path(input_path)
    archive_dir = Path(archive_dir)
    input_bytes = input_path.read_bytes()
    try:
        input_obj = json.loads(input_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"status": "INPUT_UNREADABLE",
                "reason": "input file is not valid JSON; nothing was "
                          "receipted and the pipeline was not run"}
    if not isinstance(input_obj, dict):
        return {"status": "INPUT_UNREADABLE",
                "reason": "input file is not a JSON object; nothing was "
                          "receipted and the pipeline was not run"}
    # (a) Receipt FIRST — before any model/Elo dependency runs.
    receipt_file, receipt, duplicate = rcpt.write_receipt(
        archive_dir, input_bytes, input_obj, now=now)
    receipt_id = receipt["receipt_id"]
    if duplicate:
        existing = rcpt.receipt_status(archive_dir, receipt_id)
        if existing["outcome"] is not None:
            if not rerun:
                # This exact input was already processed to a verdict.
                # Report the recorded state; never re-run or duplicate.
                return {
                    "status": "RECEIPT_DUPLICATE",
                    "receipt_id": receipt_id,
                    "receipt_path": str(receipt_file),
                    "recorded_status": existing["status"],
                    "record_path": existing["record_path"],
                    "refusal_reason": existing["refusal_reason"],
                    "pipeline_rerun": False,
                }
            # Explicit operator rerun, permitted only because an
            # outcome (possibly from reconciliation) is on record.
            return _run_pipeline(receipt, receipt["input"],
                                  input_bytes, archive_dir,
                                  runner=runner,
                                  receipt_file=receipt_file,
                                  duplicate=True, rerun=True)
        # Receipt exists but no outcome: a prior run died between
        # receipt and outcome. NEVER auto-replay — the pipeline may
        # already have archived a record. Reconcile first.
        if not reconcile:
            return {
                "status": "RECONCILIATION_REQUIRED",
                "receipt_id": receipt_id,
                "receipt_path": str(receipt_file),
                # The receipt's resolved status: PENDING_EVALUATION
                # for a bare pending receipt, INDETERMINATE when an
                # unacknowledged journal entry exists for it (the
                # entry's outcome was never durably established).
                "recorded_status": existing["status"],
                "record_path": None,
                "refusal_reason": None,
                "pipeline_rerun": False,
                "reason": "receipt exists with no committed "
                          "outcome; rerun with --reconcile to "
                          "inspect the archive before any fresh "
                          "run is permitted",
            }
        fixture_id, market, selection, line = _expected_identity(
            receipt["input"])
        outcome = rcpt.reconcile_receipt(
            archive_dir, receipt_id, fixture_id=fixture_id,
            market=market, selection=selection, line=line)
        return {
            "status": "RECONCILED",
            "receipt_id": receipt_id,
            "receipt_path": str(receipt_file),
            "recorded_status": outcome["outcome"],
            "record_path": outcome.get("record_path"),
            "refusal_reason": outcome.get("reason"),
            "pipeline_rerun": False,
        }
    # (b)+(c) Snapshot, pipeline, verified outcome.
    return _run_pipeline(receipt, input_obj, input_bytes, archive_dir,
                         runner=runner, receipt_file=receipt_file,
                         duplicate=False, rerun=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--archive-dir", type=Path,
                        default=Path("archive") / fc.ARCHIVE_DIRNAME)
    parser.add_argument("--reconcile", action="store_true",
                        help="for a receipt stuck at PENDING_EVALUATION, "
                             "inspect the archive and record what "
                             "actually happened instead of rerunning")
    parser.add_argument("--rerun", action="store_true",
                        help="explicitly request a fresh pipeline run "
                             "for a receipt that already has a recorded "
                             "outcome (e.g. after reconciliation)")
    args = parser.parse_args(argv)
    report = capture_with_receipt(args.input, args.archive_dir,
                                  reconcile=args.reconcile,
                                  rerun=args.rerun)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] == "INPUT_UNREADABLE":
        return 1
    if report["status"] in ("RECEIPT_DUPLICATE", "RECONCILED"):
        return 0 if report["recorded_status"] == rcpt.STATUS_ARCHIVED \
            else 1
    if report["status"] == "RECONCILIATION_REQUIRED":
        return 1
    return 0 if report["status"] == rcpt.STATUS_ARCHIVED else 1


if __name__ == "__main__":
    raise SystemExit(main())
