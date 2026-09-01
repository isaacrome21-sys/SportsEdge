#!/usr/bin/env python3
"""Fail-closed health check for the scheduled auto-MLB workflow.

The deadman is deliberately independent from model/promotion semantics. Its only
claim is operational: a successful auto-MLB workflow must have completed within
the configured freshness window. Any state that cannot prove that claim is
unhealthy and exits non-zero.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
from typing import Any, Iterable, Mapping


HEALTHY_CONCLUSION = "success"


def _timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("DEADMAN_TIMESTAMP_MISSING")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("DEADMAN_TIMESTAMP_NAIVE")
    return parsed.astimezone(timezone.utc)


def evaluate_runs(
    runs: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    max_age_minutes: float,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("DEADMAN_NOW_NAIVE")
    now_utc = now.astimezone(timezone.utc)
    max_age = float(max_age_minutes)
    if max_age <= 0:
        raise ValueError("DEADMAN_MAX_AGE_INVALID")

    completed = [dict(row) for row in runs if str(row.get("status") or "") == "completed"]
    if not completed:
        return {"healthy": False, "problems": ["DEADMAN_NO_COMPLETED_AUTO_MLB_RUNS"], "max_age_minutes": max_age}

    latest = max(completed, key=lambda row: str(row.get("updated_at") or row.get("run_started_at") or ""))
    stamp = latest.get("updated_at") or latest.get("run_started_at")
    if not stamp:
        return {
            "healthy": False,
            "latest_run_id": latest.get("id"),
            "latest_conclusion": latest.get("conclusion"),
            "problems": ["DEADMAN_LATEST_RUN_TIMESTAMP_MISSING"],
            "max_age_minutes": max_age,
        }

    try:
        completed_at = _timestamp(stamp)
    except (TypeError, ValueError) as exc:
        return {
            "healthy": False,
            "latest_run_id": latest.get("id"),
            "latest_conclusion": latest.get("conclusion"),
            "problems": [f"DEADMAN_LATEST_RUN_TIMESTAMP_INVALID:{type(exc).__name__}:{exc}"],
            "max_age_minutes": max_age,
        }

    age = (now_utc - completed_at).total_seconds() / 60.0
    conclusion = str(latest.get("conclusion") or "")
    problems: list[str] = []
    if age < -5.0:
        problems.append(f"DEADMAN_FUTURE_HEARTBEAT:age_minutes={age:.1f}")
    if age > max_age:
        problems.append(f"DEADMAN_STALE:age_minutes={age:.1f}:max_age_minutes={max_age:.1f}")
    if conclusion != HEALTHY_CONCLUSION:
        problems.append(f"DEADMAN_LATEST_RUN_NOT_SUCCESSFUL:conclusion={conclusion or 'missing'}")

    return {
        "healthy": not problems,
        "latest_run_id": latest.get("id"),
        "latest_conclusion": conclusion or None,
        "latest_updated_at": str(stamp),
        "age_minutes": age,
        "max_age_minutes": max_age,
        "problems": problems,
    }


def fetch_auto_mlb_runs(repo: str) -> list[dict[str, Any]]:
    repository = str(repo or "").strip()
    if not repository or "/" not in repository:
        raise ValueError("DEADMAN_REPOSITORY_INVALID")
    raw = subprocess.check_output(
        [
            "gh", "api", "--method", "GET",
            f"repos/{repository}/actions/workflows/auto-mlb.yml/runs",
            "-f", "branch=main", "-f", "per_page=10",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    payload = json.loads(raw)
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("DEADMAN_WORKFLOW_RUNS_PAYLOAD_INVALID")
    return [dict(row) for row in runs if isinstance(row, Mapping)]


def main() -> int:
    repo = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
    try:
        max_age = float(os.environ.get("MAX_AGE_MINUTES", "45"))
    except ValueError as exc:
        print(f"DEADMAN_MAX_AGE_INVALID:{exc}")
        return 2
    try:
        runs = fetch_auto_mlb_runs(repo)
    except Exception as exc:
        print(f"DEADMAN_HEARTBEAT_API_UNAVAILABLE:{type(exc).__name__}:{exc}")
        return 2
    try:
        result = evaluate_runs(runs, now=datetime.now(timezone.utc), max_age_minutes=max_age)
    except Exception as exc:
        print(f"DEADMAN_EVALUATION_ERROR:{type(exc).__name__}:{exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["healthy"]:
        print("DEADMAN_HEALTHY")
        return 0
    for problem in result["problems"]:
        print(problem)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
