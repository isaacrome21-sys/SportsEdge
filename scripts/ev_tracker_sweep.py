#!/usr/bin/env python3
"""Recover owner-created open [BET] issues that missed their issue-triggered tracker job.

The close workflow runs this under the repo-wide paid Odds API concurrency lock.
This exists because GitHub concurrency keeps at most one running and one pending
job per group; an older pending issue-triggered job can otherwise be cancelled.
"""
from __future__ import annotations

import importlib.util
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_tracker():
    spec = importlib.util.spec_from_file_location("ev_tracker_sweep_runtime", ROOT / "scripts" / "ev_tracker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tr = _load_tracker()


def list_open_owner_bets(token: str, repo: str, owner: str, opener=urllib.request.urlopen) -> list[dict]:
    query = urllib.parse.urlencode({
        "state": "open",
        "creator": owner,
        "per_page": 100,
        "sort": "created",
        "direction": "asc",
    })
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "SportsEdge-EV-Tracker",
        },
    )
    with opener(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise tr.EVError("GITHUB_ISSUES_SCHEMA")
    return [
        issue for issue in data
        if isinstance(issue, dict)
        and "pull_request" not in issue
        and str(issue.get("title", "")).startswith("[BET]")
        and (issue.get("user") or {}).get("login") == owner
    ]


def recovery_action(issue: dict) -> str:
    """Preserve original timing semantics: opened if untouched, edited otherwise."""
    return "edited" if issue.get("updated_at") and issue.get("updated_at") != issue.get("created_at") else "opened"


def sweep_open_bets(policy: dict, client, gh, owner: str, env=None, issues=None) -> list[dict]:
    issues = list(issues if issues is not None else list_open_owner_bets(gh.token, gh.repo, owner))
    results = []
    for issue in issues:
        play_id = f"issue-{issue['number']}"
        if (tr.PLAYS_DIR / f"{play_id}.json").exists():
            continue
        outcome = tr.run_log({"action": recovery_action(issue), "issue": issue}, policy, client, gh, owner, env)
        results.append({"issue": issue["number"], "outcome": outcome})
    return results


def main() -> int:
    key = os.environ.get("ODDS_API_KEY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    if not (key and token and repo and owner):
        missing = [name for name, value in (
            ("ODDS_API_KEY", key), ("GITHUB_TOKEN", token), ("GITHUB_REPOSITORY", repo),
            ("GITHUB_REPOSITORY_OWNER", owner)) if not value]
        print("SWEEP_SKIPPED_MISSING_ENV:" + ",".join(missing))
        return 0
    policy = tr.ev.load_active_policy(ROOT)
    gh = tr.GitHub(token, repo)
    client = tr.OddsApiClient(key, policy["budget"]["reserve_credits"])
    results = sweep_open_bets(policy, client, gh, owner)
    print(json.dumps({"swept": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
