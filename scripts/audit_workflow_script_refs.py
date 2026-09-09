#!/usr/bin/env python3
"""Fail closed when a GitHub Actions workflow references a repository-local script
that does not exist.

This guard is deliberately dependency-free. It parses no YAML and imports nothing
outside the standard library, because a guard that can be taken down by a CI
dependency problem cannot be trusted to report on CI dependency problems.

There is no allowlist. A workflow that references a missing script is a defect,
not a configuration option. Quarantine the workflow or write the script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Iterable

WORKFLOW_DIR = Path(".github/workflows")
WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Repository-local executable references we hold to the invariant. Extend this
# tuple rather than adding per-reference exceptions.
TRACKED_PREFIXES = ("scripts/", "ops/", "acceptance/", "tools/", "bin/")
TRACKED_SUFFIXES = (".py", ".sh")

# Anchored on the tracked prefix rather than on surrounding syntax, so a path
# stays visible through quoting, ${{ }} interpolation and shell variables.
_REF = re.compile(
    r"(?<![A-Za-z0-9_.\-])"
    r"(?:" + "|".join(re.escape(p.rstrip("/")) for p in TRACKED_PREFIXES) + r")"
    r"/[A-Za-z0-9_./\-]*"
    r"(?:" + "|".join(re.escape(s) for s in TRACKED_SUFFIXES) + r")"
    r"(?![A-Za-z0-9_.\-])"
)


class WorkflowRefError(RuntimeError):
    pass


def _candidate_paths(text: str) -> set[str]:
    """Extract repository-local script references from raw workflow text."""
    found: set[str] = set()
    for match in _REF.finditer(text):
        token, start = match.group(0), match.start()
        # Path traversal is not a repo-local reference we can resolve.
        if ".." in token.split("/"):
            continue
        before = text[:start]
        # Preceded by "/" continues a longer path (site-packages/scripts/x.py,
        # a URL path) unless the separator follows ${{ }}, $VAR or whitespace,
        # which is how a workspace-relative reference is written.
        if before.endswith("/") and not before.endswith("./"):
            head = before[:-1]
            if head and (head[-1].isalnum() or head[-1] in "._-"):
                continue
        found.add(token)
    return found


def audit(repo_root: Path, workflow_dir: Path | None = None) -> dict:
    root = repo_root.resolve()
    wf_dir = (workflow_dir or (root / WORKFLOW_DIR)).resolve()
    if not wf_dir.is_dir():
        raise WorkflowRefError(f"workflow directory not found: {wf_dir}")

    workflows = sorted(
        p for p in wf_dir.iterdir()
        if p.is_file() and p.suffix in WORKFLOW_SUFFIXES
    )
    if not workflows:
        raise WorkflowRefError(f"no workflow files found in {wf_dir}")

    missing: list[dict[str, str]] = []
    checked = 0
    for wf in workflows:
        try:
            text = wf.read_text(encoding="utf-8")
        except Exception as exc:  # unreadable workflow is itself a defect
            raise WorkflowRefError(f"unreadable workflow {wf.name}: {exc}") from exc
        for ref in sorted(_candidate_paths(text)):
            checked += 1
            if not (root / ref).is_file():
                missing.append({"workflow": wf.name, "missing_path": ref})

    return {
        "schema": "WORKFLOW_SCRIPT_REF_AUDIT_V1",
        "workflows_scanned": len(workflows),
        "references_checked": checked,
        "missing_count": len(missing),
        "missing": missing,
        "status": "FAIL" if missing else "PASS",
    }


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--workflow-dir", default=None, help="override workflow directory")
    ap.add_argument("--json", dest="json_out", default=None, help="write the audit report to this path")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.repo_root)
    wf_dir = Path(args.workflow_dir) if args.workflow_dir else None

    try:
        report = audit(root, wf_dir)
    except WorkflowRefError as exc:
        print(f"WORKFLOW_SCRIPT_REF_AUDIT_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"scanned {report['workflows_scanned']} workflows, "
        f"checked {report['references_checked']} repository-local script references"
    )
    if report["missing"]:
        print(f"\nWORKFLOW_SCRIPT_REF_AUDIT: FAIL ({report['missing_count']} missing)\n")
        width = max(len(r["workflow"]) for r in report["missing"])
        for row in report["missing"]:
            print(f"  {row['workflow']:<{width}}  ->  {row['missing_path']}")
        print(
            "\nEvery repository-local script referenced by a workflow must exist.\n"
            "Write the script, or quarantine the workflow. Do not add a stub to\n"
            "turn CI green, and do not allowlist the reference."
        )
        return 1

    print("WORKFLOW_SCRIPT_REF_AUDIT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
