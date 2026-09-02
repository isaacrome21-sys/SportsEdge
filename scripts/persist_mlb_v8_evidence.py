#!/usr/bin/env python3
"""Persist immutable MLB V8 evidence from workflow artifacts to the data branch."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

DATA_BRANCH = "data"
DEFAULT_SOURCE = Path("artifacts/mlb_v8")
WORKTREE = Path(".data-v8-branch")


class PersistError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    out = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if out.stdout:
        print(out.stdout, end="")
    if check and out.returncode != 0:
        raise PersistError(f"command failed ({out.returncode}): {' '.join(args)}")
    return out


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_tree_immutable(source: Path, destination: Path) -> tuple[int, int]:
    copied = 0
    identical = 0
    for src in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = src.relative_to(source)
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if _sha(src) != _sha(dst):
                raise PersistError(f"immutable collision at {dst}")
            identical += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
    return copied, identical


def _prepare_worktree() -> None:
    if WORKTREE.exists():
        _run(["git", "worktree", "remove", "--force", str(WORKTREE)], check=False)
        if WORKTREE.exists():
            shutil.rmtree(WORKTREE)
    _run(["git", "fetch", "--depth=1", "origin", DATA_BRANCH])
    _run(["git", "worktree", "add", "--detach", str(WORKTREE), "FETCH_HEAD"])


def _commit_and_push(*, source: Path, run_id: str) -> dict:
    destination = WORKTREE / "archive/mlb_v8"
    copied, identical = _copy_tree_immutable(source, destination)
    if copied == 0:
        return {"status": "NO_NEW_V8_EVIDENCE", "identical_files": identical}

    _run(["git", "config", "user.name", "sportsedge-v8-bot"], cwd=WORKTREE)
    _run(
        ["git", "config", "user.email", "sportsedge-v8-bot@users.noreply.github.com"],
        cwd=WORKTREE,
    )
    _run(["git", "add", "archive/mlb_v8"], cwd=WORKTREE)

    staged = _run(["git", "diff", "--cached", "--quiet"], cwd=WORKTREE, check=False)
    if staged.returncode == 0:
        return {"status": "NO_NEW_V8_EVIDENCE", "identical_files": identical}
    if staged.returncode != 1:
        raise PersistError("unable to inspect V8 staged diff")

    _run(
        ["git", "commit", "-m", f"v8: persist MLB evidence run {run_id}"],
        cwd=WORKTREE,
    )
    for attempt in range(1, 6):
        pushed = _run(
            ["git", "push", "origin", f"HEAD:{DATA_BRANCH}"],
            cwd=WORKTREE,
            check=False,
        )
        if pushed.returncode == 0:
            return {
                "status": "PERSISTED",
                "new_files": copied,
                "identical_files": identical,
                "github_run_id": run_id,
            }
        _run(["git", "fetch", "origin", DATA_BRANCH], cwd=WORKTREE)
        rebased = _run(
            ["git", "rebase", f"origin/{DATA_BRANCH}"],
            cwd=WORKTREE,
            check=False,
        )
        if rebased.returncode != 0:
            _run(["git", "rebase", "--abort"], cwd=WORKTREE, check=False)
            raise PersistError("data-branch V8 rebase conflict")
        time.sleep(attempt * 2)
    raise PersistError("data-branch V8 push failed after retries")


def _self_test() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        src = root / "source"
        dst = root / "dest"
        (src / "2026-09-03/market/a").mkdir(parents=True)
        one = src / "2026-09-03/market/a/manifest.json"
        one.write_text('{"schema_version":"SPORTSEDGE_MLB_V8_EVIDENCE_V1"}\n')
        copied, identical = _copy_tree_immutable(src, dst)
        assert (copied, identical) == (1, 0)
        copied, identical = _copy_tree_immutable(src, dst)
        assert (copied, identical) == (0, 1)
        one.write_text('{"mutated":true}\n')
        try:
            _copy_tree_immutable(src, dst)
        except PersistError:
            pass
        else:
            raise AssertionError("mutation did not fail closed")
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "immutable_copy": "PASS",
        "idempotent_replay": "PASS",
        "collision_fail_closed": "PASS",
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if args.self_test:
        return _self_test()

    if not args.source.is_dir() or not any(p.is_file() for p in args.source.rglob("*")):
        print(json.dumps({"status": "NO_V8_EVIDENCE_TO_PERSIST"}, sort_keys=True))
        return 0

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    try:
        _prepare_worktree()
        result = _commit_and_push(source=args.source, run_id=run_id)
    except Exception as exc:
        print(json.dumps({
            "status": "V8_PERSISTENCE_FAILED",
            "error": f"{type(exc).__name__}:{exc}",
            "at_utc": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True), file=sys.stderr)
        return 98
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
