#!/usr/bin/env python3
"""Audit repository-local scripts referenced by GitHub Actions workflows.

Static checkout refs are verified against the exact ref that supplies the file.
Side-by-side checkouts (``with: path: ...``) and step/job working directories are
understood. Runtime-computed checkout refs cannot be proven statically, so they
are reported explicitly instead of being misclassified as missing.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")
SCRIPT_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:\./)?((?:[A-Za-z0-9_.-]+/)*scripts/[A-Za-z0-9_./-]+\.(?:py|sh))"
)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _norm(path: str) -> str:
    value = str(PurePosixPath(path.strip() or "."))
    return "." if value in ("", ".") else value.removeprefix("./")


def _script_refs(step: dict[str, Any], working_directory: str) -> set[str]:
    refs: set[str] = set()
    for text in _strings(step.get("run")):
        for match in SCRIPT_RE.finditer(text):
            raw = _norm(match.group(1))
            workspace_path = raw if working_directory == "." else _norm(f"{working_directory}/{raw}")
            refs.add(workspace_path)
    return refs


def _checkout(step: dict[str, Any]) -> tuple[str, str] | None:
    uses = str(step.get("uses") or "")
    if not uses.startswith("actions/checkout@"):
        return None
    with_block = step.get("with") if isinstance(step.get("with"), dict) else {}
    ref = str(with_block.get("ref") or "HEAD").strip()
    path = _norm(str(with_block.get("path") or "."))
    return path, ref


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _dynamic(ref: str) -> bool:
    return "${{" in ref or "$" in ref


def _resolve_static_ref(ref: str, cache: dict[str, str]) -> str | None:
    if ref == "HEAD":
        return "HEAD"
    if ref in cache:
        return cache[ref]
    if _dynamic(ref):
        return None
    local = _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    if local.returncode == 0:
        cache[ref] = local.stdout.strip()
        return cache[ref]
    fetched = _git("fetch", "--quiet", "--depth=1", "origin", ref)
    if fetched.returncode != 0:
        return ""
    resolved = _git("rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if resolved.returncode != 0:
        return ""
    cache[ref] = resolved.stdout.strip()
    return cache[ref]


def _source_for(workspace_path: str, checkouts: dict[str, str]) -> tuple[str, str] | None:
    candidates: list[tuple[int, str, str]] = []
    for root, ref in checkouts.items():
        if root == ".":
            candidates.append((0, root, ref))
        elif workspace_path == root or workspace_path.startswith(root + "/"):
            candidates.append((len(root), root, ref))
    if not candidates:
        return None
    _, root, ref = max(candidates)
    relative = workspace_path if root == "." else workspace_path[len(root) + 1 :]
    return relative, ref


def audit() -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    ref_cache: dict[str, str] = {}

    for workflow in sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))):
        data = yaml.safe_load(workflow.read_text()) or {}
        jobs = data.get("jobs") or {}
        if not isinstance(jobs, dict):
            continue

        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            checkouts: dict[str, str] = {}
            job_defaults = ((job.get("defaults") or {}).get("run") or {}) if isinstance(job.get("defaults"), dict) else {}
            job_workdir = _norm(str(job_defaults.get("working-directory") or "."))

            for step_index, step in enumerate(job.get("steps") or [], start=1):
                if not isinstance(step, dict):
                    continue

                checkout = _checkout(step)
                if checkout is not None:
                    root, ref = checkout
                    checkouts[root] = ref
                    continue

                step_workdir = _norm(str(step.get("working-directory") or job_workdir))
                for workspace_path in sorted(_script_refs(step, step_workdir)):
                    source = _source_for(workspace_path, checkouts)
                    if source is None:
                        failures.append(
                            f"{workflow}:{job_name}:step{step_index}:{workspace_path}:NO_CHECKOUT_SUPPLIES_PATH"
                        )
                        continue

                    repo_path, ref = source
                    if _dynamic(ref):
                        warnings.append(
                            f"{workflow}:{job_name}:step{step_index}:{repo_path}:DYNAMIC_CHECKOUT_REF_RUNTIME_ONLY:{ref}"
                        )
                        continue

                    resolved = _resolve_static_ref(ref, ref_cache)
                    if resolved == "":
                        failures.append(
                            f"{workflow}:{job_name}:step{step_index}:{repo_path}:CHECKOUT_REF_NOT_FOUND:{ref}"
                        )
                        continue
                    if resolved is None:
                        warnings.append(
                            f"{workflow}:{job_name}:step{step_index}:{repo_path}:DYNAMIC_CHECKOUT_REF_RUNTIME_ONLY:{ref}"
                        )
                        continue

                    exists = Path(repo_path).is_file() if resolved == "HEAD" else _git(
                        "cat-file", "-e", f"{resolved}:{repo_path}"
                    ).returncode == 0
                    if not exists:
                        failures.append(
                            f"{workflow}:{job_name}:step{step_index}:{repo_path}:MISSING_AT_REF:{ref}"
                        )

    return failures, warnings


def main() -> int:
    failures, warnings = audit()
    for warning in warnings:
        print("WORKFLOW_SCRIPT_REFERENCE_AUDIT_WARN", warning)
    if failures:
        print("WORKFLOW_SCRIPT_REFERENCE_AUDIT_FAIL")
        for failure in failures:
            print(failure)
        return 2
    print(f"WORKFLOW_SCRIPT_REFERENCE_AUDIT_PASS warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
