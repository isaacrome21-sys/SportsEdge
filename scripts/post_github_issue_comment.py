#!/usr/bin/env python3
"""Post one GitHub issue comment using only the Python standard library."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def post_issue_comment(
    body: str,
    *,
    issue: int,
    repository: str,
    token: str,
    api_url: str = "https://api.github.com",
    opener=urlopen,
) -> None:
    if not body.strip():
        raise ValueError("COMMENT_BODY_EMPTY")
    if issue <= 0:
        raise ValueError("ISSUE_NUMBER_INVALID")
    if "/" not in repository:
        raise ValueError("GITHUB_REPOSITORY_INVALID")
    url = f"{api_url.rstrip('/')}/repos/{repository}/issues/{issue}/comments"
    req = Request(
        url,
        data=json.dumps({"body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "SportsEdge-mlb-lines-issue",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener(req, timeout=15) as response:
        status = getattr(response, "status", 201)
        if status not in {200, 201}:
            raise RuntimeError(f"GITHUB_COMMENT_POST_FAILED:{status}")
        response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True, type=int)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--body-file")
    group.add_argument("--body")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if not token:
        raise SystemExit("GITHUB_TOKEN_MISSING")
    if not repository:
        raise SystemExit("GITHUB_REPOSITORY_MISSING")
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body
    post_issue_comment(body, issue=args.issue, repository=repository, token=token, api_url=api_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
