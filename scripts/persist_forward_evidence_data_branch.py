#!/usr/bin/env python3
"""Persist prospective evidence create-only to a durable data branch.

The source checkout remains on the code revision. Evidence is copied into a
detached worktree at origin/<branch>, committed there, and pushed only to that
data branch. Existing bytes are immutable: an identity collision with different
content fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable, Sequence

NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward", "fetch first", "rejected", "behind its remote counterpart",
    "tip of your current branch is behind",
)
PERMISSION_MARKERS = (
    "permission denied", "protected branch", "not authorized", "403",
    "refusing to allow", "required status check", "pre-receive hook declined",
)
NETWORK_MARKERS = (
    "could not resolve host", "connection timed out", "connection reset",
    "unable to access", "operation timed out",
)


class PersistenceBlocked(RuntimeError):
    def __init__(self, reason: str, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def classify_push_failure(stderr: str | None) -> str:
    text = (stderr or "").lower()
    if any(marker in text for marker in PERMISSION_MARKERS):
        return "PERMISSION_DENIED"
    if any(marker in text for marker in NON_FAST_FORWARD_MARKERS):
        return "NON_FAST_FORWARD"
    if any(marker in text for marker in NETWORK_MARKERS):
        return "NETWORK"
    return "UNKNOWN"


def _run(args: Sequence[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(repo_root: Path, paths: Iterable[str]) -> list[tuple[Path, Path]]:
    rows: list[tuple[Path, Path]] = []
    root = repo_root.resolve()
    for raw in paths:
        source = (root / raw).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise PersistenceBlocked("BLOCKED_SOURCE_OUTSIDE_REPO", raw) from exc
        if not source.exists():
            continue
        if source.is_file():
            rows.append((source, source.relative_to(root)))
            continue
        if source.is_dir():
            for item in sorted(p for p in source.rglob("*") if p.is_file()):
                rows.append((item, item.relative_to(root)))
            continue
        raise PersistenceBlocked("BLOCKED_UNSUPPORTED_SOURCE", raw)
    return rows


def _copy_create_only(
    files: Sequence[tuple[Path, Path]], *, worktree: Path
) -> tuple[list[str], list[str]]:
    copied: list[str] = []
    identical: list[str] = []
    for source, relative in files:
        destination = worktree / relative
        if destination.exists():
            if not destination.is_file():
                raise PersistenceBlocked("BLOCKED_DESTINATION_NOT_FILE", str(relative))
            if _sha256(destination) != _sha256(source):
                raise PersistenceBlocked(
                    "BLOCKED_CREATE_ONLY_COLLISION",
                    {"path": str(relative), "source_sha256": _sha256(source), "existing_sha256": _sha256(destination)},
                )
            identical.append(str(relative))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(str(relative))
    return copied, identical


def _must_run(args: Sequence[str], *, cwd: Path | None = None, reason: str) -> str:
    code, out, err = _run(args, cwd=cwd)
    if code != 0:
        raise PersistenceBlocked(reason, err or out)
    return out.strip()


def _remote_head(branch: str) -> str | None:
    code, out, _ = _run(["git", "ls-remote", "origin", f"refs/heads/{branch}"])
    if code != 0 or not out.strip():
        return None
    return out.split()[0].strip()


def persist(
    *,
    paths: Sequence[str],
    branch: str = "data",
    worktree: str | Path,
    message: str = "evidence: persist prospective MLB MONEYLINE observations",
    max_attempts: int = 4,
    repo_root: str | Path = ".",
) -> dict:
    root = Path(repo_root).resolve()
    files = _source_files(root, paths)
    if not files:
        return {"status": "NOTHING_TO_PERSIST", "branch": branch, "attempts": 0, "files": 0}
    if not branch or branch in {"main", "master"}:
        raise PersistenceBlocked("BLOCKED_NON_DATA_BRANCH", branch)
    if max_attempts < 1:
        raise PersistenceBlocked("BLOCKED_INVALID_ATTEMPT_BUDGET", max_attempts)

    wt = Path(worktree).resolve()
    if wt == root or root in wt.parents:
        raise PersistenceBlocked("BLOCKED_WORKTREE_INSIDE_SOURCE_CHECKOUT", str(wt))
    if wt.exists():
        shutil.rmtree(wt)

    _must_run(["git", "fetch", "origin", branch], cwd=root, reason="BLOCKED_DATA_BRANCH_FETCH")
    _must_run(
        ["git", "worktree", "add", "--detach", str(wt), f"origin/{branch}"],
        cwd=root,
        reason="BLOCKED_DATA_WORKTREE_CREATE",
    )
    attempts: list[dict] = []
    try:
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                _must_run(["git", "fetch", "origin", branch], cwd=root, reason="BLOCKED_DATA_BRANCH_FETCH")
                _must_run(["git", "reset", "--hard", f"origin/{branch}"], cwd=wt, reason="BLOCKED_DATA_WORKTREE_RESET")
                _must_run(["git", "clean", "-fd"], cwd=wt, reason="BLOCKED_DATA_WORKTREE_CLEAN")

            copied, identical = _copy_create_only(files, worktree=wt)
            if not copied:
                return {
                    "status": "ALREADY_PERSISTED",
                    "branch": branch,
                    "attempts": attempts,
                    "files": len(files),
                    "identical": identical,
                }

            _must_run(["git", "add", "--", *copied], cwd=wt, reason="BLOCKED_DATA_GIT_ADD")
            _must_run(["git", "config", "user.name", "sportsedge-evidence-bot"], cwd=wt, reason="BLOCKED_DATA_GIT_CONFIG")
            _must_run(
                ["git", "config", "user.email", "sportsedge-evidence-bot@users.noreply.github.com"],
                cwd=wt,
                reason="BLOCKED_DATA_GIT_CONFIG",
            )
            _must_run(["git", "commit", "-m", message], cwd=wt, reason="BLOCKED_DATA_GIT_COMMIT")
            local_head = _must_run(["git", "rev-parse", "HEAD"], cwd=wt, reason="BLOCKED_DATA_LOCAL_HEAD")
            code, _, err = _run(["git", "push", "origin", f"HEAD:{branch}"], cwd=wt)
            if code == 0:
                remote = _remote_head(branch)
                if remote != local_head:
                    raise PersistenceBlocked(
                        "BLOCKED_DATA_REMOTE_VERIFY",
                        {"local_head": local_head, "remote_head": remote, "branch": branch},
                    )
                attempts.append({"attempt": attempt, "result": "PUSHED", "commit": local_head})
                return {
                    "status": "PERSISTED",
                    "branch": branch,
                    "attempts": attempts,
                    "commit": local_head,
                    "files": len(copied),
                    "identical": identical,
                }

            failure = classify_push_failure(err)
            attempts.append({"attempt": attempt, "result": failure})
            if failure == "PERMISSION_DENIED":
                raise PersistenceBlocked("BLOCKED_DATA_PERMISSION", {"attempts": attempts, "stderr": err})
            if failure not in {"NON_FAST_FORWARD", "NETWORK"}:
                raise PersistenceBlocked("BLOCKED_DATA_PUSH", {"attempts": attempts, "stderr": err})

        raise PersistenceBlocked("BLOCKED_DATA_RETRIES_EXHAUSTED", {"attempts": attempts})
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], cwd=root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--branch", default="data")
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--message", default="evidence: persist prospective MLB MONEYLINE observations")
    parser.add_argument("--max-attempts", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        result = persist(
            paths=args.path,
            branch=args.branch,
            worktree=args.worktree,
            message=args.message,
            max_attempts=args.max_attempts,
        )
    except PersistenceBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": exc.reason, "detail": exc.detail}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
