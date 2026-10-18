#!/usr/bin/env python3
"""Clean-working-tree guard.

Snapshots ``git status --porcelain --untracked-files=all`` before a test run
and afterwards reports every status entry that was not in the baseline.
A test (or code a test invokes) that writes into the repository tree -- a new
untracked file, a modified tracked file, a deletion -- produces a new entry
and fails the guard.  Baseline entries themselves never fail the check, so a
tree that was already dirty in a known way does not mask new damage.

Usage:
    python scripts/check_clean_tree.py --snapshot BASELINE_FILE
    python scripts/check_clean_tree.py --check BASELINE_FILE

The baseline file should live OUTSIDE the repository tree (for example under
$RUNNER_TEMP in CI); a baseline written inside the tree would itself appear
as a new untracked entry at check time.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def git_status_entries(root: Path) -> list[str]:
    """Current porcelain status entries for the repo at ``root``, sorted."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git status failed in {root}: {proc.stderr.strip()}")
    return sorted(line for line in proc.stdout.splitlines() if line.strip())


def new_entries(baseline: list[str], current: list[str]) -> list[str]:
    """Status entries present in ``current`` that are absent from ``baseline``."""
    base = set(baseline)
    return sorted(line for line in current if line not in base)


def repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"not inside a git work tree: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--snapshot", metavar="FILE",
                       help="write the current status entries to FILE")
    group.add_argument("--check", metavar="FILE",
                       help="fail if the current status has entries missing from FILE")
    args = ap.parse_args(argv)

    root = repo_root()
    current = git_status_entries(root)

    if args.snapshot:
        Path(args.snapshot).write_text(
            "".join(f"{line}\n" for line in current), encoding="utf-8")
        print(f"clean-tree baseline: {len(current)} entries -> {args.snapshot}")
        return 0

    baseline_file = Path(args.check)
    if not baseline_file.is_file():
        print(f"clean-tree guard: baseline file not found: {baseline_file}",
              file=sys.stderr)
        return 2
    baseline = [line for line in
                baseline_file.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    extra = new_entries(baseline, current)
    if extra:
        print("clean-tree guard FAILED: new working-tree entries appeared "
              "during the run:", file=sys.stderr)
        for line in extra:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"clean-tree guard: OK ({len(current)} entries, none new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
