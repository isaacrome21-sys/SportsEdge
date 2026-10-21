#!/usr/bin/env python3
"""Clean-working-tree guard.

Snapshots Git status, the index, and content/mode fingerprints for tracked
and nonignored untracked files. A file that was already modified or untracked
can change without producing a new status entry; content fingerprints catch
those mutations too. An unchanged dirty baseline still passes.

Usage:
    python scripts/check_clean_tree.py --snapshot BASELINE_FILE
    python scripts/check_clean_tree.py --check BASELINE_FILE

The baseline file should live OUTSIDE the repository tree (for example under
$RUNNER_TEMP in CI); a baseline written inside the tree would itself appear
as a new untracked entry at check time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

SNAPSHOT_SCHEMA = "SPORTSEDGE_CLEAN_TREE_SNAPSHOT_V2"


def _file_fingerprint(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    digest = hashlib.sha256()
    digest.update(str(stat.S_IMODE(info.st_mode)).encode("ascii") + b"\0")
    if stat.S_ISLNK(info.st_mode):
        digest.update(b"symlink\0" + os.fsencode(os.readlink(path)))
    elif stat.S_ISREG(info.st_mode):
        digest.update(b"file\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        raise RuntimeError(f"cannot fingerprint unsupported path type: {path}")
    return digest.hexdigest()


def snapshot_state(root: Path) -> dict:
    """Capture visible file contents and staged blobs, including existing dirt."""
    outputs = []
    for args in (("ls-files", "--stage", "-z"),
                 ("ls-files", "--cached", "--others", "--exclude-standard", "-z")):
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True,
                              check=False)
        if proc.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed in {root}")
        outputs.append(proc.stdout)
    names = sorted({os.fsdecode(name) for name in outputs[1].split(b"\0") if name})
    return {
        "schema": SNAPSHOT_SCHEMA,
        "entries": git_status_entries(root),
        "index_sha256": hashlib.sha256(outputs[0]).hexdigest(),
        "files": {name: _file_fingerprint(root / name) for name in names},
    }


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
                       help="write a versioned content/index snapshot to FILE")
    group.add_argument("--check", metavar="FILE",
                       help="fail if visible files or the Git index changed since FILE")
    args = ap.parse_args(argv)

    root = repo_root()
    current = snapshot_state(root)

    if args.snapshot:
        Path(args.snapshot).write_text(
            json.dumps(current, sort_keys=True) + "\n", encoding="utf-8")
        print(f"clean-tree baseline: {len(current['entries'])} entries, "
              f"{len(current['files'])} files -> {args.snapshot}")
        return 0

    baseline_file = Path(args.check)
    if not baseline_file.is_file():
        print(f"clean-tree guard: baseline file not found: {baseline_file}",
              file=sys.stderr)
        return 2
    try:
        baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
        if (not isinstance(baseline, dict)
                or baseline.get("schema") != SNAPSHOT_SCHEMA
                or not isinstance(baseline.get("entries"), list)
                or not all(isinstance(x, str) for x in baseline["entries"])
                or not isinstance(baseline.get("files"), dict)
                or not isinstance(baseline.get("index_sha256"), str)):
            raise ValueError("unsupported snapshot format; create a new snapshot")
    except (OSError, ValueError) as exc:
        print(f"clean-tree guard: invalid baseline: {exc}", file=sys.stderr)
        return 2
    extra = new_entries(baseline["entries"], current["entries"])
    changed = sorted(name for name in set(baseline["files"]) | set(current["files"])
                     if baseline["files"].get(name) != current["files"].get(name))
    index_changed = baseline["index_sha256"] != current["index_sha256"]
    if extra or changed or index_changed or baseline["entries"] != current["entries"]:
        print("clean-tree guard FAILED: working-tree or index state changed "
              "during the run:", file=sys.stderr)
        for line in extra:
            print(f"  {line}", file=sys.stderr)
        for name in changed:
            print(f"  file changed: {name!r}", file=sys.stderr)
        if index_changed:
            print("  Git index changed", file=sys.stderr)
        return 1
    print(f"clean-tree guard: OK ({len(current['entries'])} entries, "
          f"{len(current['files'])} files unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
