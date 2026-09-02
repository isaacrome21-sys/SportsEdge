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


def _git(*args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)


def _git_sha() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def _run_id(now: datetime) -> str:
    return "local:" + now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_plan(plan: dict) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")


def persist_data_branch(plan: dict, run_id: str) -> None:
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
            if STATUS_ROOT.is_dir():
                for path in STATUS_ROOT.glob("*.json"):
                    shutil.copy2(path, status_dest / path.name)
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
            write_terminal_status(
                plan=plan, run_id=run_id, git_sha=git_sha,
                model_outcome="blocked", capture_outcome="not-run", root=STATUS_ROOT,
            )
            if persist:
                persist_data_branch(plan, run_id)
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

        write_terminal_status(
            plan=plan, run_id=run_id, git_sha=git_sha,
            model_outcome=model_outcome, capture_outcome=capture_outcome, root=STATUS_ROOT,
        )
        if persist:
            persist_data_branch(plan, run_id)
        return 0 if capture_outcome == "success" or not plan.get("needs_model") else 3
    except Exception:
        # Last-chance local durability: if a plan exists, emit the same fail-closed
        # terminal record before surfacing the exception.
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
    print(json.dumps({"status": "SELF_TEST_OK", "runner_independent": True}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persist-data-branch", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return run(persist=args.persist_data_branch)


if __name__ == "__main__":
    raise SystemExit(main())
