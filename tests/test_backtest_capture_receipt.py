"""Offline contracts for the receipt-first strict capture safeguard.

The receipt layer (sportsedge/backtest/capture_receipt.py) and its
wrapper CLI (scripts/capture_strict_mlb_record_v2.py) exist so the
perishable two-sided quotes are preserved immutably BEFORE the capture
pipeline's model/Elo dependencies run. These tests prove:

  * the receipt exists before the pipeline is invoked, and survives a
    failing dependency with a REFUSED outcome appended;
  * receipts are write-once and duplicate submissions are detected,
    never duplicated;
  * the outcomes log is append-only and the receipt file is never
    mutated after creation;
  * the happy path records an ARCHIVED outcome naming the record,
    including one end-to-end run through the real (frozen) v1 CLI's
    offline refusal paths (SPREAD market / post-pitch instant), which
    never touch the network.

Nothing here prices anything or certifies forecasting skill.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sportsedge.backtest import capture_receipt as rcpt

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SCRIPT = REPO_ROOT / "scripts" / "capture_strict_mlb_record_v2.py"


def _load_v2():
    spec = importlib.util.spec_from_file_location(
        "capture_strict_mlb_record_v2", V2_SCRIPT)
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


def crash_runner(exc=None):
    def run(input_path, archive_dir):
        raise (exc or RuntimeError("dependency exploded"))
    return run


# ---------------------------------------------------------------- receipt

def test_receipt_id_is_deterministic_from_content(tmp_path):
    spec = make_input()
    raw = json.dumps(spec).encode("utf-8")
    _, receipt_a, dup_a = rcpt.write_receipt(tmp_path / "a", raw, spec)
    # Same content, different key order / whitespace -> same receipt id.
    reordered = dict(reversed(list(spec.items())))
    _, receipt_b, dup_b = rcpt.write_receipt(
        tmp_path / "b", json.dumps(reordered).encode("utf-8"), reordered)
    assert receipt_a["receipt_id"] == receipt_b["receipt_id"]
    assert not dup_a and not dup_b
    # Different quote content -> different receipt.
    changed = make_input(selection_american=-171)
    _, receipt_c, _ = rcpt.write_receipt(
        tmp_path / "c", json.dumps(changed).encode("utf-8"), changed)
    assert receipt_c["receipt_id"] != receipt_a["receipt_id"]


def test_receipt_preserves_input_verbatim_and_timestamps(tmp_path):
    spec = make_input()
    raw = json.dumps(spec, indent=2).encode("utf-8")
    _, receipt, duplicate = rcpt.write_receipt(tmp_path, raw, spec)
    assert not duplicate
    assert receipt["status"] == "PENDING_EVALUATION"
    assert receipt["input"] == spec
    assert receipt["input_sha256"] == hashlib.sha256(raw).hexdigest()
    stamps = receipt["quote_timestamps_as_supplied"]
    assert stamps["selection_captured_at_utc"] == \
        "2026-10-12T23:33:09Z"
    assert stamps["opposite_captured_at_utc"] == \
        "2026-10-12T23:33:09Z"
    assert stamps["kickoff_utc"] == KICK


def test_duplicate_submission_detected_never_duplicated(tmp_path):
    spec = make_input()
    raw = json.dumps(spec).encode("utf-8")
    path, _, dup_first = rcpt.write_receipt(tmp_path, raw, spec)
    before = path.read_bytes()
    path2, _, dup_second = rcpt.write_receipt(tmp_path, raw, spec)
    assert path == path2 and not dup_first and dup_second
    assert path.read_bytes() == before
    assert len(rcpt.read_receipts(tmp_path)) == 1


# ------------------------------------------------------- receipt-first flow

def test_receipt_written_before_failing_dependency_runs(tmp_path):
    """The Oct 12 scenario: the pipeline's dependency raises. The
    receipt must already exist when it does, and a REFUSED outcome
    naming the failure class must be appended after."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    observed = {}

    def failing_runner(input_path, archive_dir):
        receipts = rcpt.read_receipts(archive_dir)
        observed["receipts_at_pipeline_time"] = len(receipts)
        observed["status_at_pipeline_time"] = \
            rcpt.receipt_status(archive_dir,
                                receipts[0][1]["receipt_id"])["status"]
        raise RuntimeError("BACKTEST_SOURCE_UNAVAILABLE")

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=failing_runner)
    assert observed["receipts_at_pipeline_time"] == 1
    assert observed["status_at_pipeline_time"] == "PENDING_EVALUATION"
    assert report["status"] == "REFUSED"
    assert report["failure_class"] == "RuntimeError"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "REFUSED"
    assert status["refusal_reason"] == "BACKTEST_SOURCE_UNAVAILABLE"
    assert status["record_path"] is None


def test_pipeline_crash_traceback_recorded_as_refused(tmp_path):
    """A pipeline that dies with a traceback (no JSON verdict) is a
    REFUSED outcome carrying the failure class and verbatim last line —
    never mistaken for an archive."""
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    stderr = ("Traceback (most recent call last):\n"
              "  File \"outcomes.py\", line 67, in _cached_fetch\n"
              "sportsedge.backtest.outcomes.OutcomeError: "
              "BACKTEST_SOURCE_UNAVAILABLE\n")

    def crashing_runner(input_path, archive_dir):
        return {"exit_code": 1, "stdout": "", "stderr": stderr}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=crashing_runner)
    assert report["status"] == "REFUSED"
    assert report["failure_class"] == \
        "sportsedge.backtest.outcomes.OutcomeError"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["outcome"]["crash"] is True
    assert status["outcome"]["reason"].endswith(
        "BACKTEST_SOURCE_UNAVAILABLE")


def test_pipeline_refusal_verdict_recorded_verbatim(tmp_path):
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    reason = ("EXISTING_MODEL_PROBABILITY_UNAVAILABLE_FOR_MARKET:SPREAD "
              "(Elo floor is ML-only in v1)")

    def refusing_runner(input_path, archive_dir):
        return {"exit_code": 1,
                "stdout": json.dumps({"status": "CAPTURE_REFUSED",
                                      "reason": reason}),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner)
    assert report["status"] == "REFUSED"
    assert report["refusal_reason"] == reason
    assert report["failure_class"] is None


def write_valid_record(input_path, archive_dir,
                       name="fixture__ML__HOME.json"):
    """Write an archived record the way the real v1 CLI does: correct
    fixture identity and provenance input_sha256 = SHA-256 of the
    input file bytes it consumed (here: the receipt snapshot)."""
    from sportsedge.backtest import forward_capture as fc
    spec = json.loads(Path(input_path).read_text(encoding="utf-8"))
    captures = Path(archive_dir) / "captures"
    captures.mkdir(parents=True, exist_ok=True)
    record = {
        "fixture_id": fc.fixture_id_for(spec["away"], spec["home"],
                                        spec["kickoff_utc"]),
        "market": str(spec["market"]).upper(),
        "selection": str(spec["selection"]).upper(),
        # The real v1 record always carries a line; modeled
        # faithfully because verification requires it (#2086 r2).
        "line": "ML" if str(spec["market"]).upper() == "ML"
                else float(spec["line"]),
        "capture_provenance": {
            "input_sha256": hashlib.sha256(
                Path(input_path).read_bytes()).hexdigest()},
    }
    path = captures / name
    path.write_text(json.dumps(record, indent=2, sort_keys=True),
                    encoding="utf-8")
    return path, record


def test_happy_path_archived_outcome_and_record(tmp_path):
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def ok_runner(input_path, archive_dir):
        # Mimic the v1 CLI: write a well-formed record into captures/
        # (provenance + identity included — a bare "{}" record is the
        # audit-#2086 false-success defect and now verifies as
        # REFUSED), then print the pretty-printed CAPTURED verdict.
        record, record_obj = write_valid_record(input_path, archive_dir)
        verdict = {"status": "CAPTURED", "file": str(record),
                   "fixture_id": record_obj["fixture_id"],
                   "candidate_p": 0.63, "existing_p": 0.55,
                   "model_source_sha": "b" * 40,
                   "compliance_warnings": []}
        return {"exit_code": 0,
                "stdout": json.dumps(verdict, indent=2, sort_keys=True),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=ok_runner)
    assert report["status"] == "ARCHIVED"
    assert report["record_path"].endswith("fixture__ML__HOME.json")
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "ARCHIVED"
    assert status["record_path"] == report["record_path"]
    assert status["outcome"]["candidate_p"] == 0.63


def test_duplicate_after_outcome_does_not_rerun_pipeline(tmp_path):
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)
    calls = []

    def refusing_runner(input_path, archive_dir):
        calls.append(1)
        return {"exit_code": 1,
                "stdout": json.dumps({"status": "CAPTURE_REFUSED",
                                      "reason": "SOME_REFUSAL"}),
                "stderr": ""}

    first = v2.capture_with_receipt(input_file, archive,
                                    runner=refusing_runner)
    second = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner)
    assert first["status"] == "REFUSED"
    assert second["status"] == "RECEIPT_DUPLICATE"
    assert second["recorded_status"] == "REFUSED"
    assert second["refusal_reason"] == "SOME_REFUSAL"
    assert len(calls) == 1  # pipeline ran exactly once
    assert len(rcpt.read_outcomes(archive)) == 1


def test_outcomes_append_only_and_receipt_never_mutated(tmp_path):
    archive = tmp_path / "archive"
    input_file = write_input(tmp_path)

    def refusing_runner(input_path, archive_dir):
        return {"exit_code": 1,
                "stdout": json.dumps({"status": "CAPTURE_REFUSED",
                                      "reason": "R1"}),
                "stderr": ""}

    report = v2.capture_with_receipt(input_file, archive,
                                     runner=refusing_runner)
    receipt_file = Path(report["receipt_path"])
    digest_before = hashlib.sha256(receipt_file.read_bytes()).hexdigest()
    lines_before = len(rcpt.read_outcomes(archive))
    # A later appended outcome (e.g. an auditor's recovery note) must
    # not touch the receipt, and must extend — never rewrite — the log.
    rcpt.append_outcome(archive, {
        "receipt_id": report["receipt_id"], "outcome": "REFUSED",
        "reason": "R2", "failure_class": "AuditorNote"})
    assert hashlib.sha256(receipt_file.read_bytes()).hexdigest() == \
        digest_before
    assert len(rcpt.read_outcomes(archive)) == lines_before + 1
    # Latest outcome is the effective state.
    assert rcpt.receipt_status(archive, report["receipt_id"])[
        "refusal_reason"] == "R2"
    listed = rcpt.list_receipts(archive)
    assert [item["receipt_id"] for item in listed] == \
        [report["receipt_id"]]
    assert listed[0]["status"] == "REFUSED"


def test_unreadable_input_receipts_nothing(tmp_path):
    archive = tmp_path / "archive"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    report = v2.capture_with_receipt(bad, archive,
                                     runner=crash_runner())
    assert report["status"] == "INPUT_UNREADABLE"
    assert rcpt.read_receipts(archive) == []


# ------------------------------------------- end-to-end via the real v1 CLI

def _run_v2_cli(tmp_path, spec):
    input_file = write_input(tmp_path, spec)
    archive = tmp_path / "archive"
    proc = subprocess.run(
        [sys.executable, str(V2_SCRIPT), "--input", str(input_file),
         "--archive-dir", str(archive)],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    return proc, archive


def test_end_to_end_spread_refusal_is_receipted(tmp_path):
    """The real v1 CLI refuses SPREAD before any network/model work;
    the wrapper must still have preserved the quotes first."""
    proc, archive = _run_v2_cli(tmp_path, make_input(market="SPREAD",
                                                     line=-1.5))
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["status"] == "REFUSED"
    assert "EXISTING_MODEL_PROBABILITY_UNAVAILABLE_FOR_MARKET" in \
        report["refusal_reason"]
    receipts = rcpt.read_receipts(archive)
    assert len(receipts) == 1
    assert receipts[0][1]["input"]["market"] == "SPREAD"
    status = rcpt.receipt_status(archive, report["receipt_id"])
    assert status["status"] == "REFUSED"
    # And no evaluator record was archived.
    assert not (archive / "captures").exists()


def test_end_to_end_post_pitch_refusal_is_receipted(tmp_path):
    """A capture attempted after first pitch refuses in the v1 CLI
    (as_of check runs before pricing/Elo), and is still receipted."""
    proc, archive = _run_v2_cli(
        tmp_path, make_input(kickoff_utc="2020-10-13T00:00:00Z",
                             selection_captured_at_utc=
                             "2020-10-12T23:33:09Z",
                             opposite_captured_at_utc=
                             "2020-10-12T23:33:09Z"))
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["status"] == "REFUSED"
    assert "AS_OF_NOT_PREGAME" in report["refusal_reason"]
    assert len(rcpt.read_receipts(archive)) == 1
