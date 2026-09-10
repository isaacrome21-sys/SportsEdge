#!/usr/bin/env python3
"""Fail CI when a paid The Odds API workflow can run outside the repo-wide lock.

The audit is intentionally credential-name based: a job that receives one of the
recognized The Odds API secrets is capable of spending account credits and must
serialize with every other such job. OddsPapi uses SPORTSEDGE_ODDSPAPI_KEY and
is a distinct provider, so it is deliberately outside this contract.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import yaml

WORKFLOW_ROOT = Path(".github/workflows")
LOCK_GROUP = "sportsedge-paid-odds-api"
SECRET_RE = re.compile(
    r"\$\{\{\s*secrets\.(?:SPORTSEDGE_)?ODDS_API_KEY(?:_[2-4])?\s*\}\}"
)


def _uses_paid_secret(value: Any) -> bool:
    # PyYAML 6 still applies YAML 1.1 scalar rules and can decode keys such as
    # ``on`` as booleans. Do not sort mapping keys here: mixed bool/string keys
    # are valid parser output and their order is irrelevant to secret detection.
    return bool(SECRET_RE.search(json.dumps(value, default=str)))


def _lock_ok(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    group = str(value.get("group") or "").strip()
    cancel = value.get("cancel-in-progress")
    return group == LOCK_GROUP and cancel is False


def audit() -> list[str]:
    failures: list[str] = []
    audited_jobs = 0
    for path in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        try:
            payload = yaml.safe_load(text) or {}
        except Exception as exc:
            failures.append(f"{path}:YAML_PARSE_FAILED:{type(exc).__name__}:{exc}")
            continue
        if not isinstance(payload, Mapping):
            failures.append(f"{path}:WORKFLOW_NOT_MAPPING")
            continue

        top_lock_ok = _lock_ok(payload.get("concurrency"))
        jobs = payload.get("jobs") or {}
        if not isinstance(jobs, Mapping):
            failures.append(f"{path}:JOBS_NOT_MAPPING")
            continue

        for job_name, job in jobs.items():
            if not isinstance(job, Mapping) or not _uses_paid_secret(job):
                continue
            audited_jobs += 1
            if top_lock_ok or _lock_ok(job.get("concurrency")):
                continue
            failures.append(
                f"{path}:job={job_name}:PAID_ODDS_API_JOB_MISSING_GLOBAL_LOCK:"
                f"required_group={LOCK_GROUP}:cancel_in_progress=false"
            )

        # A workflow-level secret can be inherited by jobs without appearing in
        # the individual job mapping. If that occurs, the workflow itself must
        # carry the global lock.
        top_level = dict(payload)
        top_level.pop("jobs", None)
        if _uses_paid_secret(top_level) and not top_lock_ok:
            failures.append(
                f"{path}:workflow:PAID_ODDS_API_TOP_LEVEL_SECRET_MISSING_GLOBAL_LOCK:"
                f"required_group={LOCK_GROUP}:cancel_in_progress=false"
            )

    if audited_jobs == 0:
        failures.append("NO_PAID_ODDS_API_JOBS_DISCOVERED")
    return failures


def main() -> int:
    failures = audit()
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"PAID_ODDS_API_CONCURRENCY_OK:{LOCK_GROUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
