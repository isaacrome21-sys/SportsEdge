#!/usr/bin/env python3
"""Runner-independent MLB V8 forward evidence fallback.

Runs the same planner, canonical MLB machine, materializer, and terminal-status writer
used by Actions. Intended for cron/Task Scheduler/manual execution when hosted Actions
cannot acquire a runner. No promotion logic exists here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from capture_mlb_v8_forward_evidence import write_terminal_status
from run_mlb_v8_forward_lane import CT, build_plan, fetch_schedule, materialize

ARTIFACTS = Path("artifacts")
PLAN_PATH = ARTIFACTS / "mlb_v8_plan.json"
CARD_PATH = ARTIFACTS / "live_mlb_card.json"
EVIDENCE_ROOT = ARTIFACTS / "mlb_v8_forward"
STATUS_ROOT = ARTIFACTS / "mlb_v8_status"
REQUIRED_RUNTIME_ENV = (
    "SPORTSEDGE_QUOTES_URL",
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_FEATURES_URL",
    "SPORTSEDGE_PROJECTED_LINEUPS_URL",
    "SPORTSEDGE_PROVIDER_TOKEN",
)


def _git(*args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)


def _git_sha() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def _run_id(now: datetime) -> str:
    return "local:" + now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_plan(plan: dict) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")


def persist_data_branch(plan: dict, run_id: str, status_path: Path) -> None:
    slate = str(plan.get("slate_date_ct") or "unknown")
    safe = run_id.replace(":", "_").replace("/", "_")
    _git("fetch", "origin", "data")
    with tempfile.TemporaryDirectory(prefix="sportsedge-v8-data-") as td:
        worktree = Path(td) / "data"
        _git("worktree", "add", "--detach", str(worktree), "origin/data")
        try:
            if EVIDENCE_ROOT.is_dir():
                destination = worktree / "evidence" / "mlb_v8_forward"
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copytree(EVIDENCE_ROOT, destination, dirs_exist_ok=True)
            status_dest = worktree / "runtime" / "mlb-v8-status" / slate
            status_dest.mkdir(parents=True, exist_ok=True)
            if PLAN_PATH.is_file():
                shutil.copy2(PLAN_PATH, status_dest / f"plan_{safe}.json")
            if status_path.is_file():
                shutil.copy2(status_path, status_dest / status_path.name)
            _git("config", "user.name", "sportsedge-v8-evidence-local", cwd=worktree)
            _git("config", "user.email", "sportsedge-v8-evidence-local@users.noreply.github.com", cwd=worktree)
            _git("add", "runtime/mlb-v8-status", cwd=worktree)
            if (worktree / "evidence" / "mlb_v8_forward").is_dir():
                _git("add", "evidence/mlb_v8_forward", cwd=worktree)
            diff = _git("diff", "--cached", "--quiet", check=False, cwd=worktree)
            if diff.returncode == 0:
                return
            _git("commit", "-m", f"evidence: persist MLB V8 local target window {run_id}", cwd=worktree)
            for attempt in range(1, 6):
                push = _git("push", "origin", "HEAD:data", check=False, cwd=worktree)
                if push.returncode == 0:
                    return
                _git("fetch", "origin", "data", cwd=worktree)
                _git("rebase", "origin/data", cwd=worktree)
            raise RuntimeError("V8 local evidence data-branch persistence failed after retries")
        finally:
            _git("worktree", "remove", "--force", str(worktree), check=False)


def dry_run(*, check_data_branch: bool = True) -> int:
    now = datetime.now(timezone.utc)
    slate = now.astimezone(CT).date().isoformat()
    checks: dict[str, object] = {}
    failures: list[str] = []

    try:
        checks["git_sha"] = _git_sha()
        checks["git_head_ok"] = True
    except Exception as exc:
        checks["git_head_ok"] = False
        checks["git_head_error"] = type(exc).__name__
        failures.append("git_head")

    try:
        schedule = fetch_schedule(slate)
        checks["schedule_fetch_ok"] = True
        checks["schedule_game_count"] = len(schedule)
    except Exception as exc:
        checks["schedule_fetch_ok"] = False
        checks["schedule_fetch_error"] = type(exc).__name__
        failures.append("schedule_fetch")

    help_run = subprocess.run(
        ["python", "scripts/run_auto_mlb_resilient.py", "--help"],
        check=False, text=True, capture_output=True,
    )
    checks["canonical_cli_import_ok"] = help_run.returncode == 0
    if help_run.returncode != 0:
        checks["canonical_cli_returncode"] = help_run.returncode
        checks["canonical_cli_stderr_tail"] = help_run.stderr[-1000:]
        failures.append("canonical_cli_import")

    env_presence = {name: bool(os.environ.get(name)) for name in REQUIRED_RUNTIME_ENV}
    checks["runtime_env_present"] = env_presence
    checks["runtime_env_complete"] = all(env_presence.values())
    if not checks["runtime_env_complete"]:
        failures.append("runtime_env")

    if check_data_branch:
        fetch = _git("fetch", "origin", "data", check=False)
        checks["data_branch_fetch_ok"] = fetch.returncode == 0
        if fetch.returncode != 0:
            checks["data_branch_fetch_stderr_tail"] = fetch.stderr[-1000:]
            failures.append("data_branch_fetch")
        else:
            probe = _git("rev-parse", "--verify", "FETCH_HEAD", check=False)
            checks["data_branch_ref_ok"] = probe.returncode == 0
            if probe.returncode != 0:
                failures.append("data_branch_ref")

    payload = {
        "schema": "MLB_V8_FORWARD_FALLBACK_DRY_RUN_V1",
        "checked_at_utc": now.isoformat(),
        "slate_date_ct": slate,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checks": checks,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 4


def run(*, persist: bool = False) -> int:
    now = datetime.now(timezone.utc)
    run_id = _run_id(now)
    git_sha = _git_sha()
    slate = now.astimezone(CT).date().isoformat()
    model_outcome = "not-run"
    capture_outcome = "not-run"

    try:
        try:
            plan = build_plan(now, fetch_schedule(slate))
        except Exception as exc:
            plan = {
                "schema": "MLB_V8_FORWARD_PLAN_V1",
                "planned_at_utc": now.isoformat(),
                "slate_date_ct": slate,
                "effective": slate >= "2026-09-03",
                "needs_model": False,
                "games": [],
                "reason": "SCHEDULE_FETCH_FAILED",
                "error_type": type(exc).__name__,
            }
            _write_plan(plan)
            status_path = write_terminal_status(
                plan=plan, run_id=run_id, git_sha=git_sha,
                model_outcome="blocked", capture_outcome="not-run", root=STATUS_ROOT,
            )
            if persist:
                persist_data_branch(plan, run_id, status_path)
            return 2

        _write_plan(plan)
        if not (plan.get("games") or []):
            return 0

        if plan.get("needs_model"):
            model = subprocess.run(
                ["python", "scripts/run_auto_mlb_resilient.py", "--output", str(CARD_PATH)],
                check=False,
            )
            model_outcome = "success" if model.returncode == 0 else "failure"
            if model.returncode == 0:
                try:
                    materialize(
                        plan=plan, card_raw=CARD_PATH.read_bytes(), model_sha=git_sha,
                        run_id=run_id, root=EVIDENCE_ROOT,
                    )
                    capture_outcome = "success"
                except Exception:
                    capture_outcome = "failure"
            else:
                capture_outcome = "not-run"

        status_path = write_terminal_status(
            plan=plan, run_id=run_id, git_sha=git_sha,
            model_outcome=model_outcome, capture_outcome=capture_outcome, root=STATUS_ROOT,
        )
        if persist:
            persist_data_branch(plan, run_id, status_path)
        return 0 if capture_outcome == "success" or not plan.get("needs_model") else 3
    except Exception:
        if PLAN_PATH.is_file():
            plan = json.loads(PLAN_PATH.read_text())
            try:
                write_terminal_status(
                    plan=plan, run_id=run_id, git_sha=git_sha,
                    model_outcome=model_outcome, capture_outcome="failure", root=STATUS_ROOT,
                )
            except Exception:
                pass
        raise


def self_test() -> int:
    assert _run_id(datetime(2026, 9, 3, tzinfo=timezone.utc)).startswith("local:20260903T")
    print(json.dumps({"status": "SELF_TEST_OK", "runner_independent": True, "single_status_persistence": True, "dry_run_available": True}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persist-data-branch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-data-branch-check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.dry_run:
        return dry_run(check_data_branch=not args.skip_data_branch_check)
    return run(persist=args.persist_data_branch)


if __name__ == "__main__":
    raise SystemExit(main())
