#!/usr/bin/env python3
"""Fail when a GitHub Actions job references a repository-local script absent from
that job's active checkout ref.

The audit is checkout-ref aware: workflows that deliberately checkout a frozen
branch/tag are validated against that ref rather than the branch running CI.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")
SCRIPT_RE = re.compile(r"(?<![A-Za-z0-9_.-])(?:\./)?(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))")


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _script_refs(step: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for text in _strings(step.get("run")):
        refs.update(m.group(1) for m in SCRIPT_RE.finditer(text))
    return refs


def _checkout_ref(step: dict[str, Any]) -> str | None:
    uses = str(step.get("uses") or "")
    if not uses.startswith("actions/checkout@"):
        return None
    raw = (step.get("with") or {}).get("ref") if isinstance(step.get("with"), dict) else None
    if raw is None or str(raw).strip() == "":
        return "HEAD"
    return str(raw).strip()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _resolve_ref(ref: str, cache: dict[str, str]) -> str | None:
    if ref == "HEAD":
        return "HEAD"
    if ref in cache:
        return cache[ref]
    if "${{" in ref or "$" in ref:
        return None
    local = _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    if local.returncode == 0:
        cache[ref] = local.stdout.strip()
        return cache[ref]
    fetched = _git("fetch", "--quiet", "--depth=1", "origin", ref)
    if fetched.returncode != 0:
        return None
    resolved = _git("rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if resolved.returncode != 0:
        return None
    cache[ref] = resolved.stdout.strip()
    return cache[ref]


def _exists(path: str, ref: str, cache: dict[str, str]) -> tuple[bool, str | None]:
    resolved = _resolve_ref(ref, cache)
    if resolved is None:
        return False, None
    if resolved == "HEAD":
        return Path(path).is_file(), resolved
    check = _git("cat-file", "-e", f"{resolved}:{path}")
    return check.returncode == 0, resolved


def audit() -> list[str]:
    failures: list[str] = []
    ref_cache: dict[str, str] = {}
    for workflow in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
        data = yaml.safe_load(workflow.read_text()) or {}
        jobs = data.get("jobs") or {}
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            active_ref = "HEAD"
            for step_index, step in enumerate(job.get("steps") or [], start=1):
                if not isinstance(step, dict):
                    continue
                checkout = _checkout_ref(step)
                if checkout is not None:
                    active_ref = checkout
                    continue
                for path in sorted(_script_refs(step)):
                    exists, resolved = _exists(path, active_ref, ref_cache)
                    if not exists:
                        if resolved is None:
                            failures.append(
                                f"{workflow}:{job_name}:step{step_index}:{path}:UNRESOLVED_CHECKOUT_REF:{active_ref}"
                            )
                        else:
                            failures.append(
                                f"{workflow}:{job_name}:step{step_index}:{path}:MISSING_AT_REF:{active_ref}"
                            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    failures = audit()
    if failures:
        print("WORKFLOW_SCRIPT_REFERENCE_AUDIT_FAIL")
        for failure in failures:
            print(failure)
        return 2
    print("WORKFLOW_SCRIPT_REFERENCE_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
