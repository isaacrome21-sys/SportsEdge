"""NFL anytime-TD v1.1 — server-side provenance (DRAFT, pending owner freeze).

Records live on ONE named records branch at fixed paths:
  fetch records  nfl_atd_v1_1/fetch/<data sha256>.json   (one per data file)
  run records    nfl_atd_v1_1/runs/<slate_id>.json
  verdict        nfl_atd_v1_1/VERDICT.json
A record's time is the GitHub SERVER-SIDE timestamp of the push that
delivered the commit adding it, read from the repository activity API
(GET /repos/{owner}/{repo}/activity, activity_type=push, field `timestamp`,
matched on `after` == the commit that added the file). Client-set author /
committer dates are never consulted. If no such push event is found the
time is UNPROVEN and fails closed (note: the activity API only lists recent
history, so proofs must be taken and recorded at run time).

Rules: the pricer refuses unless every data file's sha256 matches a fetch
record on the branch whose push is server-timed strictly before the entry
capture. A slate COUNTS only if its fetch records are pushed before capture
and its run record is pushed before the slate's first kickoff; else SCREEN.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime

OWNER, REPO = "isaacrome21-sys", "SportsEdge"
RECORDS_BRANCH = "records/nfl-atd-v1-1"
ROOT = "nfl_atd_v1_1"
VERDICT_PATH = f"{ROOT}/VERDICT.json"
SERVER_TIME_SOURCE = "GET /repos/{owner}/{repo}/activity (activity_type=push, timestamp)"


def fetch_record_path(sha256: str) -> str:
    return f"{ROOT}/fetch/{sha256}.json"


def run_record_path(slate_id: str) -> str:
    return f"{ROOT}/runs/{slate_id}.json"


class ProvenanceFailed(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _t(s) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("naive time")
    return t


class GitHubAPI:
    """Minimal read-only REST client. Uses $GITHUB_TOKEN if set (raises the
    rate limit); otherwise anonymous (public repo)."""
    def __init__(self, owner=OWNER, repo=REPO, token=None):
        self.base = f"https://api.github.com/repos/{owner}/{repo}"
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def _get(self, url, raw=False):
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        return b.decode() if raw else json.loads(b)

    def get_file(self, branch, path):
        from urllib.parse import quote
        return self._get(f"{self.base}/contents/{quote(path)}?ref={quote(branch, safe='')}", raw=True)

    def file_commits(self, branch, path):
        from urllib.parse import quote
        out, page = [], 1
        while True:
            js = self._get(f"{self.base}/commits?sha={quote(branch, safe='')}"
                           f"&path={quote(path)}&per_page=100&page={page}") or []
            out += [c["sha"] for c in js]
            if len(js) < 100:
                return out          # newest first; last = commit that added it
            page += 1

    def push_activities(self, branch):
        """All push activities for the ref, following Link rel=next."""
        import re
        from urllib.parse import quote
        url = (f"{self.base}/activity?ref={quote('refs/heads/' + branch, safe='')}"
               f"&activity_type=push&per_page=100")
        out = []
        while url:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                out += json.loads(r.read())
                m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
            url = m.group(1) if m else None
        return out


def server_pushed_at(api, branch, path):
    """Server timestamp of the push whose `after` is the commit that added
    `path` on `branch`; None if unproven."""
    commits = api.file_commits(branch, path)
    if not commits:
        return None
    added = commits[-1]
    times = [_t(p["timestamp"]) for p in api.push_activities(branch)
             if p.get("after") == added and p.get("activity_type", "push") == "push"]
    return min(times) if times else None


def verify_fetch(api, sha256, captured_at):
    path = fetch_record_path(sha256)
    content = api.get_file(RECORDS_BRANCH, path)
    if content is None:
        raise ProvenanceFailed("FETCH_RECORD_NOT_ON_BRANCH", path)
    try:
        rec = json.loads(content)
    except ValueError:
        raise ProvenanceFailed("FETCH_RECORD_HASH_MISMATCH", "unreadable record")
    if rec.get("sha256") != sha256:
        raise ProvenanceFailed("FETCH_RECORD_HASH_MISMATCH", path)
    t = server_pushed_at(api, RECORDS_BRANCH, path)
    if t is None:
        raise ProvenanceFailed("FETCH_PUSH_UNPROVEN", path)
    if t >= _t(captured_at):
        raise ProvenanceFailed("FETCH_PUSH_NOT_BEFORE_CAPTURE",
                               f"{path} pushed {t.isoformat()} >= capture {captured_at}")
    return {"path": path, "branch": RECORDS_BRANCH, "record": rec,
            "server_pushed_at": t.isoformat(), "source": SERVER_TIME_SOURCE}


def require_fetch_provenance(api, shas: dict, captured_at) -> dict:
    """Pricer gate: every data file (name -> sha256) must be proven."""
    return {name: verify_fetch(api, sha, captured_at) for name, sha in shas.items()}


def slate_status(api, slate) -> dict:
    """COUNTS iff fetch records pushed before capture AND run record pushed
    before the slate's first kickoff (server-side times); else SCREEN."""
    reasons, out = [], {}
    for k in ("stats_sha256", "schedule_sha256"):
        try:
            out[k + "_fetch"] = verify_fetch(api, slate[k], slate["captured_at"])
        except (ProvenanceFailed, KeyError, ValueError) as e:
            reasons.append(getattr(e, "code", "FETCH_RECORD_NOT_ON_BRANCH"))
    path = run_record_path(slate["slate_id"])
    if api.get_file(RECORDS_BRANCH, path) is None:
        reasons.append("RUN_RECORD_NOT_ON_BRANCH")
    else:
        t = server_pushed_at(api, RECORDS_BRANCH, path)
        if t is None:
            reasons.append("RUN_PUSH_UNPROVEN")
        else:
            out["run_server_pushed_at"] = t.isoformat()
            if t >= _t(slate["first_kickoff"]):
                reasons.append("RUN_PUSH_NOT_BEFORE_KICKOFF")
    return {"slate_id": slate["slate_id"],
            "status": "SCREEN" if reasons else "COUNTS",
            "reasons": sorted(set(reasons)), "source": SERVER_TIME_SOURCE, **out}
