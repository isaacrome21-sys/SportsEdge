"""Dry-run harness for the owner receipt infrastructure.

**Development verification only.** Isaac's Oct 12 2026 ruling:
receipt-infrastructure development and DRY-RUN verification may
proceed; activation may not. This harness exercises the owner
receipt format (``receipt_format.py``) together with the
receipt-first safeguard (``capture_receipt.py``) and the frozen
capture CLI end-to-end, on offline fixtures, inside a sandbox
archive that is **technically incapable of being the production
archive**:

- ``assert_sandbox_archive`` refuses — before anything is
  written — any archive directory that IS the production archive
  (``archive/strict-forward-capture``), contains it, is contained
  by it, sits anywhere inside the repository's ``archive/`` tree,
  or whose own name lacks the ``dry-run`` token. The harness has
  no default archive path; a sandbox must be named explicitly.

Three scenarios, each in its own clearly-named dry-run archive:

(a) **ARCHIVED-in-sandbox** — owner receipt issued over the
    capture input (effective availability pinned to the
    payload-carried quote timestamp), then the real wrapper
    (real receipt, real frozen-input snapshot, real archived-
    record verification, real ACK journal) drives the real v1 CLI
    to a CAPTURED verdict; the stored outcome must carry the
    CLI's Elo schedule provenance unchanged and the owner receipt
    must re-validate from disk afterwards.
(b) **REFUSED** — a stale fixture (its kickoff is already past at
    the run instant) refuses in the real v1 CLI
    (``AS_OF_NOT_PREGAME``) before any pricing; the outcome is
    REFUSED and the quotes survive verbatim in the receipt.
(c) **INDETERMINATE** — a child process writes one complete
    outcome entry line into the sandbox journal and is SIGKILLed
    before the ACK (real process death, the audit #2086 crash
    window). The receipt resolves to INDETERMINATE, and
    reconciliation through the real wrapper supersedes the
    never-durable claim with a committed INDETERMINATE outcome;
    the ghost entry stays preserved in the journal.

Offline fixture seams (the same documented seams the project's
own integration check uses, and the only ones): the v1 CLI's
schedule getter (``_default_schedule_getter``) returns a local
StatsAPI-shaped payload; its clock seam (``_utcnow``) is pinned
just before the fixture's first pitch; ``production_probability``
is replaced at its seam because the frozen production pricer
fail-closes OFFLINE by design (its prepricing gate cannot verify
a fixture without live sources). Everything else — pricer record
assembly, Elo leg, provenance machinery, receipt layer, snapshot,
verification, journal, reconciliation — is the real code. **No
live capture is attempted, no production archive is touched, and
nothing here activates anything.**
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import signal
import subprocess
import sys

from . import capture_receipt as rcpt
from . import forward_capture as fc
from . import receipt_format as rf

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ARCHIVE_REL = Path("archive") / fc.ARCHIVE_DIRNAME
DRY_RUN_TOKEN = "dry-run"

# Fixture identity (synthetic; mirrors the integration check).
KICKOFF_UTC = "2027-04-01T23:05:00Z"
PINNED_NOW = datetime(2027, 4, 1, 22, 40, tzinfo=timezone.utc)
QUOTE_AT = "2027-04-01T22:40:00Z"  # 1500s before first pitch, paired
CLE = "Cleveland Guardians"
TB = "Tampa Bay Rays"

# Scenario (b): a stale fixture — first pitch long past at run time.
STALE_KICKOFF_UTC = "2020-10-13T00:00:00Z"
STALE_QUOTE_AT = "2020-10-12T23:33:09Z"
STALE_OBSERVED_AT = "2020-10-13T00:10:00Z"


class DryRunError(ValueError):
    pass


# ------------------------------------------------------------- sandbox guard

def production_archive_dir(repo_root=None):
    return (Path(repo_root or REPO_ROOT) / PRODUCTION_ARCHIVE_REL)


def assert_sandbox_archive(archive_dir, *, repo_root=None):
    """Refuse any archive dir that could be the production archive.

    Checked before a single byte is written, in this order:
    production identity/containment, repository archive tree,
    dry-run naming. Returns the resolved sandbox path.
    """
    repo_root = Path(repo_root or REPO_ROOT)
    resolved = Path(archive_dir).resolve()
    prod = production_archive_dir(repo_root).resolve()
    if resolved == prod or prod in resolved.parents \
            or resolved in prod.parents:
        raise DryRunError(
            "DRY_RUN_ARCHIVE_IS_PRODUCTION: " + str(resolved))
    repo_archive = (repo_root / "archive").resolve()
    if resolved == repo_archive or repo_archive in resolved.parents:
        raise DryRunError(
            "DRY_RUN_ARCHIVE_INSIDE_REPO_ARCHIVE_TREE: "
            + str(resolved))
    if DRY_RUN_TOKEN not in resolved.name:
        raise DryRunError(
            "DRY_RUN_ARCHIVE_NAME_MISSING_TOKEN: sandbox archive "
            "directories must be clearly named with 'dry-run': "
            + str(resolved))
    return resolved


def _tree_digest(root):
    """SHA-256 over (relative path, bytes) of every file under root
    — the production archive's before/after fingerprint."""
    root = Path(root)
    digest = hashlib.sha256()
    if not root.is_dir():
        return "ABSENT"
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------- CLI loading

def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v1_module():
    return _load_module(
        "capture_strict_mlb_record_dryrun",
        REPO_ROOT / "scripts" / "capture_strict_mlb_record.py")


def _v2_module():
    return _load_module(
        "capture_strict_mlb_record_v2_dryrun",
        REPO_ROOT / "scripts" / "capture_strict_mlb_record_v2.py")


def _game(pk, date, away, home, away_score, home_score):
    return {"gamePk": pk, "gameDate": date, "gameType": "R",
            "status": {"detailedState": "Final"},
            "teams": {"away": {"team": {"name": away},
                               "score": away_score},
                      "home": {"team": {"name": home},
                               "score": home_score}}}


def _schedule_payload():
    """StatsAPI-shaped payload: three Final regular-season games,
    two involving the fixture teams, all before kickoff."""
    return {"dates": [
        {"date": "2026-10-08", "games": [
            _game(1, "2026-10-08T23:05:00Z", CLE, TB, 2, 5)]},
        {"date": "2026-10-09", "games": [
            _game(2, "2026-10-09T23:05:00Z", TB, CLE, 3, 1)]},
        {"date": "2026-10-10", "games": [
            _game(3, "2026-10-10T23:05:00Z", "New York Yankees",
                  "Boston Red Sox", 4, 6)]},
    ]}


def _production_fixture(payload_row, now):
    """Stand-in at the frozen pricer's own seam (see module
    docstring): a fixed, clearly-labeled candidate so the real CLI
    can reach its CAPTURED verdict offline."""
    return 0.60, {
        "candidate": {"lane": "LANE_A_INDEPENDENT",
                      "label": "MARKET_BLIND", "win_p": 0.60,
                      "push_p": 0.0, "loss_p": 0.40},
        "market_anchored": None,
    }, {"status": "PRICED_OFFLINE_FIXTURE"}


def _capture_input(**overrides):
    spec = {
        "schema": "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1",
        "away": CLE, "home": TB,
        "kickoff_utc": KICKOFF_UTC, "series_id": "2027-DRYRUN-CLE-TB",
        "market": "ML", "selection": "HOME", "line": "ML",
        "book": "draftkings",
        "selection_american": -163,
        "selection_captured_at_utc": QUOTE_AT,
        "opposite_american": 145,
        "opposite_captured_at_utc": QUOTE_AT,
        "quote_source": "dry-run offline fixture (no live capture)",
    }
    spec.update(overrides)
    return spec


def _issue_owner_receipt(archive_dir, input_bytes, spec, *,
                         observed_at):
    """Owner-envelope issuance over the capture input payload.

    Effective availability is pinned to the quote timestamp the
    payload itself carries (basis SOURCE_TIMESTAMP): the quote
    evidence became available when the book's price was captured,
    which the payload states and the envelope may not contradict.
    """
    envelope = rf.build_owner_receipt(
        input_bytes,
        fixture_id=fc.fixture_id_for(spec["away"], spec["home"],
                                     spec["kickoff_utc"]),
        participants=[
            {"participant_id": "team:" + spec["away"], "role": "AWAY"},
            {"participant_id": "team:" + spec["home"], "role": "HOME"},
        ],
        observed_at=observed_at,
        effective_at=spec["selection_captured_at_utc"],
        effective_at_basis=rf.BASIS_SOURCE_TIMESTAMP,
        effective_at_basis_field="selection_captured_at_utc",
        provenance={
            "source_name": "DRY_RUN_FIXTURE",
            "retrieval_path": "offline fixture issued by "
                              "receipt_dry_run (development only)",
        },
        now=PINNED_NOW)
    path, _dup = rf.write_owner_receipt(archive_dir, envelope)
    return path, envelope


def _write_input(work_dir, spec):
    path = Path(work_dir) / "capture_input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------- scenario (a)

def run_scenario_archived(sandbox_root, *, repo_root=None):
    """(a) Valid dry-run capture -> ARCHIVED-in-sandbox."""
    repo_root = Path(repo_root or REPO_ROOT)
    archive = assert_sandbox_archive(
        Path(sandbox_root) / "dry-run-archive-archived",
        repo_root=repo_root)
    work = Path(sandbox_root) / "work-archived"
    spec = _capture_input()
    input_path = _write_input(work, spec)
    input_bytes = input_path.read_bytes()
    owner_path, envelope = _issue_owner_receipt(
        archive, input_bytes, spec, observed_at=PINNED_NOW)

    cap = _v1_module()
    v2 = _v2_module()
    cap.SCHEDULE_CACHE_DIR = work / "schedule_cache"
    cap._default_schedule_getter = lambda url: _schedule_payload()
    cap._utcnow = lambda: PINNED_NOW
    cap.production_probability = _production_fixture
    captured = {}

    def runner(cli_input_path, cli_archive_dir):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cap.main(["--input", str(cli_input_path),
                           "--archive-dir", str(cli_archive_dir)])
        captured["stdout"] = out.getvalue()
        return {"exit_code": rc, "stdout": out.getvalue(),
                "stderr": err.getvalue()}

    report = v2.capture_with_receipt(input_path, archive,
                                     runner=runner)
    checks = []
    checks.append(("wrapper_status_archived",
                   report["status"] == rcpt.STATUS_ARCHIVED))
    verdict = json.loads(captured["stdout"])
    checks.append(("cli_verdict_captured",
                   verdict.get("status") == "CAPTURED"))
    record_path = Path(report["record_path"])
    checks.append(("record_exists_in_sandbox",
                   record_path.is_file()
                   and archive in record_path.resolve().parents))
    entries = rcpt.read_outcomes(archive)
    stored = [e for e in entries
              if e.get("receipt_id") == report["receipt_id"]
              and e.get("outcome") == rcpt.STATUS_ARCHIVED]
    checks.append(("one_archived_outcome", len(stored) == 1))
    checks.append(("record_verified_by_wrapper",
                   bool(stored) and stored[0].get(
                       "record_verified") is True))
    checks.append((
        "elo_provenance_intact",
        bool(stored) and stored[0].get("elo_schedule_provenance")
        == verdict.get("elo_schedule_provenance")))
    status = rcpt.receipt_status(archive, report["receipt_id"])
    checks.append(("quotes_preserved_verbatim",
                   status["receipt"]["input"] == spec))
    stored_envelope = rf.read_owner_receipt(owner_path)
    checks.append(("owner_receipt_revalidates_from_disk",
                   stored_envelope["payload_sha256"]
                   == hashlib.sha256(input_bytes).hexdigest()
                   and stored_envelope["envelope_id"]
                   == envelope["envelope_id"]))
    return _scenario_result("archived", archive, checks, {
        "receipt_id": report["receipt_id"],
        "record_path": report["record_path"],
        "owner_envelope_id": envelope["envelope_id"],
        "effective_at_utc": envelope["effective_at_utc"],
        "effective_at_basis": envelope["effective_at_basis"],
    })


# ------------------------------------------------------------- scenario (b)

def run_scenario_refused(sandbox_root, *, repo_root=None):
    """(b) Stale fixture -> real CLI refusal -> REFUSED, quotes kept."""
    repo_root = Path(repo_root or REPO_ROOT)
    archive = assert_sandbox_archive(
        Path(sandbox_root) / "dry-run-archive-refused",
        repo_root=repo_root)
    work = Path(sandbox_root) / "work-refused"
    spec = _capture_input(
        kickoff_utc=STALE_KICKOFF_UTC, series_id="2020-DRYRUN-CLE-TB",
        selection_captured_at_utc=STALE_QUOTE_AT,
        opposite_captured_at_utc=STALE_QUOTE_AT)
    input_path = _write_input(work, spec)
    input_bytes = input_path.read_bytes()
    owner_path, envelope = _issue_owner_receipt(
        archive, input_bytes, spec, observed_at=STALE_OBSERVED_AT)

    cap = _v1_module()
    v2 = _v2_module()

    def runner(cli_input_path, cli_archive_dir):
        # No seams fixtured at all: the v1 CLI refuses a stale
        # (post-first-pitch) capture before pricing or Elo, so the
        # refusal path runs entirely on real code.
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cap.main(["--input", str(cli_input_path),
                           "--archive-dir", str(cli_archive_dir)])
        return {"exit_code": rc, "stdout": out.getvalue(),
                "stderr": err.getvalue()}

    report = v2.capture_with_receipt(input_path, archive,
                                     runner=runner)
    checks = []
    checks.append(("wrapper_status_refused",
                   report["status"] == rcpt.STATUS_REFUSED))
    checks.append(("refusal_reason_is_as_of_not_pregame",
                   "AS_OF_NOT_PREGAME" in
                   (report.get("refusal_reason") or "")))
    status = rcpt.receipt_status(archive, report["receipt_id"])
    checks.append(("receipt_status_refused",
                   status["status"] == rcpt.STATUS_REFUSED))
    checks.append(("quotes_preserved_verbatim",
                   status["receipt"]["input"] == spec))
    checks.append(("no_evaluator_record_archived",
                   not (archive / "captures").exists()))
    stored_envelope = rf.read_owner_receipt(owner_path)
    checks.append(("owner_receipt_revalidates_from_disk",
                   stored_envelope["envelope_id"]
                   == envelope["envelope_id"]))
    return _scenario_result("refused", archive, checks, {
        "receipt_id": report["receipt_id"],
        "refusal_reason": report.get("refusal_reason"),
        "owner_envelope_id": envelope["envelope_id"],
    })


# ------------------------------------------------------------- scenario (c)

_DIE_WRITING_CHILD = (
    "import os, signal, sys\n"
    "fd = os.open(sys.argv[1],\n"
    "             os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)\n"
    "os.write(fd, sys.argv[2].encode('utf-8'))\n"
    "os.kill(os.getpid(), signal.SIGKILL)\n"
)


def run_scenario_indeterminate(sandbox_root, *, repo_root=None):
    """(c) Writer killed mid-append -> reconcile -> INDETERMINATE."""
    repo_root = Path(repo_root or REPO_ROOT)
    archive = assert_sandbox_archive(
        Path(sandbox_root) / "dry-run-archive-indeterminate",
        repo_root=repo_root)
    work = Path(sandbox_root) / "work-indeterminate"
    spec = _capture_input()
    input_path = _write_input(work, spec)
    input_bytes = input_path.read_bytes()
    _owner_path, envelope = _issue_owner_receipt(
        archive, input_bytes, spec, observed_at=PINNED_NOW)

    # Receipt issuance + frozen-input snapshot (the first half of
    # a real run) — then the run's process dies mid-append.
    _path, receipt, _dup = rcpt.write_receipt(
        archive, input_bytes, spec, now=PINNED_NOW)
    receipt_id = receipt["receipt_id"]
    rcpt.ensure_input_snapshot(archive, receipt_id, input_bytes,
                               receipt["input_sha256"])
    ghost = {
        "outcome": rcpt.STATUS_ARCHIVED,
        "receipt_id": receipt_id,
        "record_path": str(archive / "captures" / "ghost.json"),
        "fixture_id": fc.fixture_id_for(spec["away"], spec["home"],
                                        spec["kickoff_utc"]),
        "record_verified": True,
        "input_source": "RECEIPT_SNAPSHOT",
        "outcome_schema": rcpt.OUTCOME_SCHEMA,
        "recorded_at_utc": "2027-04-01T22:41:00Z",
    }
    ghost_line = json.dumps(ghost, sort_keys=True)
    ghost_sha = hashlib.sha256(ghost_line.encode("utf-8")).hexdigest()
    journal = rcpt.outcomes_path(archive)
    journal.parent.mkdir(parents=True, exist_ok=True)
    child = work / "die_writing_child.py"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.write_text(_DIE_WRITING_CHILD, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(child), str(journal), ghost_line + "\n"],
        capture_output=True, text=True, timeout=60)
    checks = []
    checks.append(("child_died_by_sigkill",
                   proc.returncode == -signal.SIGKILL))
    pre = rcpt.receipt_status(archive, receipt_id)
    checks.append(("pre_reconcile_status_indeterminate",
                   pre["status"] == rcpt.STATUS_INDETERMINATE))
    checks.append(("ghost_reported_unacknowledged",
                   pre["unacknowledged_entry_sha256"] == ghost_sha))
    checks.append(("no_committed_outcome_yet",
                   rcpt.read_outcomes(archive) == []))

    def exploding_runner(cli_input_path, cli_archive_dir):
        raise AssertionError(
            "reconciliation must never run the pipeline")

    v2 = _v2_module()
    report = v2.capture_with_receipt(input_path, archive,
                                     runner=exploding_runner,
                                     reconcile=True)
    checks.append(("wrapper_reconciled",
                   report["status"] == "RECONCILED"))
    checks.append(("recorded_status_indeterminate",
                   report["recorded_status"]
                   == rcpt.STATUS_INDETERMINATE))
    entries = rcpt.read_outcomes(archive)
    superseding = [e for e in entries
                   if e.get("outcome") == rcpt.STATUS_INDETERMINATE]
    checks.append(("one_committed_indeterminate_outcome",
                   len(entries) == 1 and len(superseding) == 1))
    checks.append((
        "supersede_reason_recorded",
        bool(superseding) and superseding[0].get("reason")
        == "UNACKNOWLEDGED_OUTCOME_NOT_DURABLY_ESTABLISHED"))
    checks.append((
        "ghost_preserved_unacknowledged",
        [u["sha256"] for u in rcpt.unacknowledged_outcomes(archive)]
        == [ghost_sha]))
    final = rcpt.receipt_status(archive, receipt_id)
    checks.append(("final_status_indeterminate",
                   final["status"] == rcpt.STATUS_INDETERMINATE))
    return _scenario_result("indeterminate", archive, checks, {
        "receipt_id": receipt_id,
        "ghost_entry_sha256": ghost_sha,
        "owner_envelope_id": envelope["envelope_id"],
    })


# ------------------------------------------------------------- driver

def _scenario_result(name, archive, checks, detail):
    failed = [label for label, ok in checks if not ok]
    return {
        "scenario": name,
        "archive_dir": str(archive),
        "passed": not failed,
        "checks": [{"check": label, "ok": bool(ok)}
                   for label, ok in checks],
        "failed_checks": failed,
        "detail": detail,
    }


def run_all_dry_runs(sandbox_root, *, repo_root=None):
    """Run all three scenarios under ``sandbox_root``.

    The production archive's tree digest is taken before and
    after; any change fails the run. Returns the report dict.
    """
    repo_root = Path(repo_root or REPO_ROOT)
    sandbox_root = Path(sandbox_root)
    prod = production_archive_dir(repo_root)
    before = _tree_digest(prod)
    scenarios = [
        run_scenario_archived(sandbox_root, repo_root=repo_root),
        run_scenario_refused(sandbox_root, repo_root=repo_root),
        run_scenario_indeterminate(sandbox_root, repo_root=repo_root),
    ]
    after = _tree_digest(prod)
    return {
        "dry_run": True,
        "activation": "NOT_ACTIVATED — development verification "
                      "only (owner HOLD in force)",
        "sandbox_root": str(sandbox_root),
        "production_archive": str(prod),
        "production_archive_digest_before": before,
        "production_archive_digest_after": after,
        "production_archive_untouched": before == after,
        "scenarios": scenarios,
        "all_passed": all(s["passed"] for s in scenarios)
        and before == after,
    }
