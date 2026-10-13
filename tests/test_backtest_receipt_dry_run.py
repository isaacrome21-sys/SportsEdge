"""Dry-run verification of the owner receipt infrastructure.

Development only (owner HOLD in force): these tests run the
dry-run harness (sportsedge/backtest/receipt_dry_run.py) — owner
receipt issuance, the frozen-input snapshot, the real capture CLI
and wrapper, and the ACK outcome journal — inside tmp sandboxes,
and prove the sandbox guard makes the production archive
unreachable:

  * the guard refuses the production archive path itself, any
    directory inside the repository's archive/ tree, and any
    directory not clearly named with the dry-run token;
  * scenario (a): a valid dry-run capture reaches
    ARCHIVED-in-sandbox with provenance intact;
  * scenario (b): a stale fixture records REFUSED with the quotes
    preserved verbatim;
  * scenario (c): a writer killed mid-append (real SIGKILL)
    reconciles to INDETERMINATE, the ghost entry preserved.

No live capture is attempted and the production archive's tree
digest is asserted unchanged across every run.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sportsedge.backtest import capture_receipt as rcpt
from sportsedge.backtest import receipt_dry_run as dr

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SCRIPT = REPO_ROOT / "scripts" / "dry_run_receipt_infra.py"


# ------------------------------------------------------------- sandbox guard

def test_guard_refuses_the_production_archive_itself():
    with pytest.raises(dr.DryRunError) as excinfo:
        dr.assert_sandbox_archive(dr.production_archive_dir(),
                                  repo_root=REPO_ROOT)
    assert "DRY_RUN_ARCHIVE_IS_PRODUCTION" in str(excinfo.value)


def test_guard_refuses_anything_inside_repo_archive_tree():
    with pytest.raises(dr.DryRunError) as excinfo:
        dr.assert_sandbox_archive(
            REPO_ROOT / "archive" / "dry-run-sneaky",
            repo_root=REPO_ROOT)
    assert "DRY_RUN_ARCHIVE_INSIDE_REPO_ARCHIVE_TREE" in \
        str(excinfo.value)


def test_guard_requires_the_dry_run_token(tmp_path):
    with pytest.raises(dr.DryRunError) as excinfo:
        dr.assert_sandbox_archive(tmp_path / "archive",
                                  repo_root=REPO_ROOT)
    assert "DRY_RUN_ARCHIVE_NAME_MISSING_TOKEN" in str(excinfo.value)
    ok = dr.assert_sandbox_archive(tmp_path / "dry-run-archive",
                                   repo_root=REPO_ROOT)
    assert ok.name == "dry-run-archive"


def test_harness_attempt_on_production_tree_fails_and_writes_nothing():
    """Point the harness at the repository's archive tree: every
    scenario must refuse at the guard, before any write, and the
    production archive must remain byte-identical."""
    prod = dr.production_archive_dir(REPO_ROOT)
    before = dr._tree_digest(prod)
    for scenario in (dr.run_scenario_archived, dr.run_scenario_refused,
                     dr.run_scenario_indeterminate):
        with pytest.raises(dr.DryRunError):
            scenario(REPO_ROOT / "archive", repo_root=REPO_ROOT)
    assert dr._tree_digest(prod) == before


# ------------------------------------------------------------- scenarios

def test_all_three_scenarios_pass_in_sandbox(tmp_path):
    report = dr.run_all_dry_runs(tmp_path / "sandbox",
                                 repo_root=REPO_ROOT)
    assert report["dry_run"] is True
    assert report["production_archive_untouched"] is True
    assert report["all_passed"] is True, report
    by_name = {s["scenario"]: s for s in report["scenarios"]}
    assert set(by_name) == {"archived", "refused", "indeterminate"}
    for scenario in by_name.values():
        assert scenario["passed"], scenario["failed_checks"]
        assert "dry-run" in Path(scenario["archive_dir"]).name


def test_archived_scenario_leaves_auditable_sandbox_state(tmp_path):
    report = dr.run_all_dry_runs(tmp_path / "sandbox",
                                 repo_root=REPO_ROOT)
    archived = [s for s in report["scenarios"]
                if s["scenario"] == "archived"][0]
    archive = Path(archived["archive_dir"])
    record = Path(archived["detail"]["record_path"])
    assert record.is_file() and archive in record.parents
    status = rcpt.receipt_status(
        archive, archived["detail"]["receipt_id"])
    assert status["status"] == "ARCHIVED"
    assert status["outcome"]["record_verified"] is True
    # The owner receipt sits alongside the safeguard receipts and
    # still validates from disk after the run.
    from sportsedge.backtest import receipt_format as rf
    envelopes = rf.list_owner_receipts(archive)
    assert [e["envelope_id"] for e in envelopes] == [
        archived["detail"]["owner_envelope_id"]]
    assert envelopes[0]["effective_at_utc"] == "2027-04-01T22:40:00Z"
    assert envelopes[0]["effective_at_basis"] == "SOURCE_TIMESTAMP"


def test_cli_script_runs_sandbox_and_refuses_repo_archive(tmp_path):
    ok = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--sandbox-root",
         str(tmp_path / "sandbox")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        timeout=300)
    assert ok.returncode == 0, ok.stderr
    report = json.loads(ok.stdout)
    assert report["all_passed"] is True

    refused = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--sandbox-root",
         str(REPO_ROOT / "archive")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        timeout=60)
    assert refused.returncode == 2
    assert json.loads(refused.stdout)["status"] == "DRY_RUN_REFUSED"
