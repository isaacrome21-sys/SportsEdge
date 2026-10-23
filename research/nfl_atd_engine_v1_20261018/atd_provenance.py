"""NFL anytime-TD v1.1 — server-side provenance (DRAFT, pending owner freeze).

Records live on ONE named records branch at fixed paths:
  fetch records  nfl_atd_v1_1/fetch/<data sha256>.json
  run records    nfl_atd_v1_1/runs/<slate_id>.json
  verdict        nfl_atd_v1_1/VERDICT.json
Rules (re-audit rulings A-G):
 A  a record path has exactly ONE commit ever (no edit, delete or re-add);
    the blob at that commit equals the blob at the branch head; any
    force_push or branch_deletion activity on the records branch refuses.
 C  fetch push < run push, and captured_at <= run push < first kickoff.
 F  server time = GitHub repository activity API event
    (GET /repos/{owner}/{repo}/activity: id, before, after, timestamp,
    activity_type) whose `after` is the record's commit. The raw fetch
    events are stored in the run record at run time; at review a live match
    OR the stored event cross-checked against the commits API (after == the
    record's single commit, before == its only parent) is accepted. The
    activity API keeps roughly 90 days of history; past that only stored
    events can prove a time. The run record's own push must be proven live
    (review within ~90 days of the slate) or the slate is SCREEN.
 G  one commit per push: the event's `before` must be the commit's only
    parent. Malformed / failing API responses are coded refusals.
Client-set author / committer dates are never consulted.
Recommended (owner action, not enforceable here): branch protection on
records/* forbidding force-push and deletion.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import quote

OWNER, REPO = "isaacrome21-sys", "sportsedge"
ORIGIN_CANONICAL = f"github.com/{OWNER}/{REPO}"
RECORDS_BRANCH = "records/nfl-atd-v1-1"
ROOT = "nfl_atd_v1_1"
VERDICT_PATH = f"{ROOT}/VERDICT.json"
SERVER_TIME_SOURCE = "GET /repos/{owner}/{repo}/activity (activity_type=push, timestamp)"
REWRITE_TYPES = {"force_push", "branch_deletion"}
CLOSE_PUSH_GRACE = timedelta(minutes=15)   # close push <= kickoff + 15 min
FINAL_BUFFER = timedelta(hours=4)          # game final = kickoff + 4 h (same as refresh)


def fetch_record_path(sha256: str) -> str:
    return f"{ROOT}/fetch/{sha256}.json"


def run_record_path(slate_id: str) -> str:
    return f"{ROOT}/runs/{slate_id}.json"


def close_record_path(sha256: str) -> str:
    return f"{ROOT}/closes/{sha256}.json"


def settlement_data_path(sha256: str) -> str:
    return f"{ROOT}/settlements/{sha256}.json"


class ProvenanceFailed(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _t(s) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("naive time")
    return t


def _call(fn, *a):
    try:
        return fn(*a)
    except ProvenanceFailed:
        raise
    except (OSError, urllib.error.URLError) as e:
        raise ProvenanceFailed("API_UNAVAILABLE", f"{getattr(fn, '__name__', fn)}: {e}")
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ProvenanceFailed("API_MALFORMED", f"{getattr(fn, '__name__', fn)}: {e}")


class GitHubAPI:
    """Read-only REST client (anonymous for the public repo, or $GITHUB_TOKEN)."""
    def __init__(self, owner=OWNER, repo=REPO, token=None):
        self.base = f"https://api.github.com/repos/{owner}/{repo}"
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def _req(self, url):
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        try:
            r = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (404, 409):
                return None, {}
            raise
        with r:
            return json.loads(r.read()), r.headers

    def _contents(self, ref, path):
        js, _ = self._req(f"{self.base}/contents/{quote(path)}?ref={quote(ref, safe='')}")
        return js

    def get_file(self, ref, path):
        js = self._contents(ref, path)
        if js is None:
            return None
        return base64.b64decode(js["content"]).decode()

    def blob_sha(self, ref, path):
        js = self._contents(ref, path)
        return None if js is None else js["sha"]

    def file_commits(self, branch, path):
        out, page = [], 1
        while True:
            js, _ = self._req(f"{self.base}/commits?sha={quote(branch, safe='')}"
                              f"&path={quote(path)}&per_page=100&page={page}")
            js = js or []
            out += [c["sha"] for c in js]
            if len(js) < 100:
                return out
            page += 1

    def list_dir(self, ref, path):
        js = self._contents(ref, path)
        if js is None:
            return []
        return [e["name"] for e in js]

    def commit_info(self, sha):
        js, _ = self._req(f"{self.base}/commits/{sha}")
        return js

    def activities(self, branch):
        """ALL activity types for the ref (push, force_push, branch_deletion…)."""
        url = (f"{self.base}/activity?ref={quote('refs/heads/' + branch, safe='')}"
               f"&per_page=100")
        out = []
        while url:
            js, h = self._req(url)
            out += js or []
            m = re.search(r'<([^>]+)>;\s*rel="next"', (h or {}).get("Link") or "")
            url = m.group(1) if m else None
        return out


_EV_KEYS = ("id", "before", "after", "timestamp", "activity_type")


def _events(api):
    evs = _call(api.activities, RECORDS_BRANCH)
    if not isinstance(evs, list):
        raise ProvenanceFailed("API_MALFORMED", "activities not a list")
    out = []
    for e in evs:
        if not isinstance(e, dict) or not all(k in e for k in _EV_KEYS):
            raise ProvenanceFailed("API_MALFORMED", f"activity event {e!r}")
        _t(e["timestamp"])
        out.append({k: e[k] for k in _EV_KEYS})
    bad = [e for e in out if e["activity_type"] in REWRITE_TYPES]
    if bad:
        raise ProvenanceFailed("RECORDS_BRANCH_REWRITTEN",
                               f"{bad[0]['activity_type']} id={bad[0]['id']}")
    return out


def _only_parent(api, sha):
    info = _call(api.commit_info, sha)
    try:
        parents = [p["sha"] for p in info["parents"]]
    except (TypeError, KeyError) as e:
        raise ProvenanceFailed("API_MALFORMED", f"commit {sha}: {e}")
    if len(parents) != 1:
        raise ProvenanceFailed("PUSH_NOT_SINGLE_COMMIT", f"{sha} has {len(parents)} parents")
    return parents[0]


def prove_record(api, path, stored_event=None) -> dict:
    """Prove a record's single commit and its server push time (rules A, F, G)."""
    events = _events(api)                           # refuses rewrites first
    commits = _call(api.file_commits, RECORDS_BRANCH, path)
    if not isinstance(commits, list) or not all(isinstance(c, str) for c in commits):
        raise ProvenanceFailed("API_MALFORMED", "file_commits")
    head = _call(api.get_file, RECORDS_BRANCH, path)
    if head is not None and not isinstance(head, str):
        raise ProvenanceFailed("API_MALFORMED", "get_file")
    if not commits:
        raise ProvenanceFailed("RECORD_NOT_ON_BRANCH", path)
    if len(commits) != 1 or head is None:
        raise ProvenanceFailed("RECORD_NOT_SINGLE_COMMIT", f"{path}: {len(commits)} commits")
    c = commits[0]
    b_commit = _call(api.blob_sha, c, path)
    b_head = _call(api.blob_sha, RECORDS_BRANCH, path)
    if b_commit is None or b_commit != b_head:
        raise ProvenanceFailed("RECORD_BLOB_MISMATCH", path)
    parent = _only_parent(api, c)
    live = [e for e in events if e["after"] == c and e["activity_type"] == "push"]
    if live:
        ev = min(live, key=lambda e: _t(e["timestamp"]))
        if ev["before"] != parent:
            raise ProvenanceFailed("PUSH_NOT_SINGLE_COMMIT",
                                   f"push {ev['id']} before={ev['before']} parent={parent}")
        src = "live_activity"
    elif stored_event is not None:
        if not isinstance(stored_event, dict) or not all(k in stored_event for k in _EV_KEYS):
            raise ProvenanceFailed("API_MALFORMED", "stored event incomplete")
        ev = {k: stored_event[k] for k in _EV_KEYS}
        if ev["after"] != c or ev["before"] != parent or ev["activity_type"] != "push":
            raise ProvenanceFailed("STORED_EVENT_MISMATCH", f"{path}")
        src = "stored_event_commit_checked"
    else:
        raise ProvenanceFailed("PUSH_UNPROVEN", path)
    try:
        t = _t(ev["timestamp"])
    except ValueError:
        raise ProvenanceFailed("API_MALFORMED", "event timestamp")
    return {"path": path, "commit": c, "event": ev, "pushed_at": t.isoformat(),
            "proof_source": src, "source": SERVER_TIME_SOURCE, "content": head}


def verify_fetch(api, sha256, captured_at, stored_event=None):
    path = fetch_record_path(sha256)
    try:
        p = prove_record(api, path, stored_event)
    except ProvenanceFailed as e:
        code = e.code if e.code.startswith(("API_", "RECORDS_")) else "FETCH_" + e.code
        raise ProvenanceFailed(code, e.detail)
    try:
        rec = json.loads(p["content"])
        ok = rec.get("sha256") == sha256
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        raise ProvenanceFailed("FETCH_RECORD_HASH_MISMATCH", path)
    if captured_at is not None and _t(p["pushed_at"]) >= _t(captured_at):
        raise ProvenanceFailed("FETCH_PUSH_NOT_BEFORE_CAPTURE",
                               f"{path} pushed {p['pushed_at']} >= capture {captured_at}")
    p.pop("content")
    return p


def require_fetch_provenance(api, shas: dict, captured_at) -> dict:
    """Pricer gate; returns proofs incl. the raw events to store (rule F)."""
    return {name: verify_fetch(api, sha, captured_at) for name, sha in shas.items()}


def load_slate(api, slate_id) -> dict:
    """Load a slate ONLY from its pushed run record at the branch head (rule
    B) and decide COUNTS / SCREEN (rules A, C, F)."""
    path = run_record_path(slate_id)
    out = {"slate_id": slate_id, "status": "SCREEN", "reasons": [], "record": None,
           "content": None}
    try:
        rp = prove_record(api, path)
    except ProvenanceFailed as e:
        out["reasons"].append(e.code if e.code.startswith(("API_", "RECORDS_"))
                              else "RUN_" + e.code)
        return out
    out["run_proof"] = {k: v for k, v in rp.items() if k != "content"}
    out["content"] = rp["content"]
    try:
        rec = json.loads(rp["content"])
        cap, ko = _t(rec["captured_at"]), _t(rec["first_kickoff"])
        shas = {"stats": rec["stats_sha256"], "schedule": rec["schedule_sha256"]}
        stored = rec.get("fetch_provenance") or {}
        rows = rec["rows"]
        if rec.get("slate_id") != slate_id or not isinstance(rows, list):
            raise ValueError("slate_id/rows")
    except (ValueError, KeyError, TypeError):
        out["reasons"].append("RUN_RECORD_MALFORMED")
        return out
    run_t = _t(rp["pushed_at"])
    if run_t < cap:
        out["reasons"].append("RUN_PUSH_BEFORE_CAPTURE")
    if run_t >= ko:
        out["reasons"].append("RUN_PUSH_NOT_BEFORE_KICKOFF")
    for name, sha in shas.items():
        ev = (stored.get(name) or {}).get("event") if isinstance(stored, dict) else None
        try:
            fp = verify_fetch(api, sha, None, ev)
            ft = _t(fp["pushed_at"])
            if ft >= cap:
                out["reasons"].append("FETCH_PUSH_NOT_BEFORE_CAPTURE")
            if ft >= run_t:
                out["reasons"].append("FETCH_PUSH_NOT_BEFORE_RUN_PUSH")
            out[f"{name}_fetch_proof"] = fp
        except ProvenanceFailed as e:
            out["reasons"].append(e.code)
    out["record"] = rec
    out["reasons"] = sorted(set(out["reasons"]))
    out["status"] = "SCREEN" if out["reasons"] else "COUNTS"
    return out


def _list(api, sub):
    names = _call(api.list_dir, RECORDS_BRANCH, f"{ROOT}/{sub}")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ProvenanceFailed("API_MALFORMED", f"list_dir {sub}")
    return sorted(n for n in names if n.endswith(".json"))


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def load_closes(api) -> dict:
    """Close captures ONLY from single-commit records closes/<sha256>.json
    (sha256 of the file content). A record is proven iff its server push is
    >= its captured_at (and every entry's captured_at) and <= kickoff + 15
    min. Any unproven record for a game marks the WHOLE game unproven."""
    out = {"captures": [], "unproven_games": [], "unproven_records": [],
           "kickoffs": {}, "records": []}
    bad_games = set()
    for name in _list(api, "closes"):
        path = f"{ROOT}/closes/{name}"
        game = None
        try:
            head = _call(api.get_file, RECORDS_BRANCH, path)
            try:
                body = json.loads(head)
                game = body.get("game_id")
            except (TypeError, ValueError, AttributeError):
                body = None
            p = prove_record(api, path)
            if _sha_text(p["content"]) != name[:-5] or body is None:
                raise ProvenanceFailed("CLOSE_RECORD_HASH_MISMATCH", path)
            ko = _t(body["kickoff"])
            push = _t(p["pushed_at"])
            if push < _t(body["captured_at"]) or push > ko + CLOSE_PUSH_GRACE:
                raise ProvenanceFailed("CLOSE_PUSH_OUTSIDE_WINDOW", path)
            for c in body["captures"]:
                try:
                    ct = _t(c.get("captured_at"))
                except (ValueError, TypeError):
                    continue        # surfaces as CLOSE_TIMESTAMP_INVALID when scored
                if ct > push:
                    raise ProvenanceFailed("CLOSE_PUSH_OUTSIDE_WINDOW", f"{path}: entry after push")
            if game in out["kickoffs"] and out["kickoffs"][game] != body["kickoff"]:
                raise ProvenanceFailed("CLOSE_KICKOFF_CONFLICT", path)
            out["kickoffs"][game] = body["kickoff"]
            out["captures"] += [dict(c, game_id=game) for c in body["captures"]]
            out["records"].append({"path": path, "commit": p["commit"],
                                   "pushed_at": p["pushed_at"], "sha256": name[:-5]})
        except (ProvenanceFailed, KeyError, TypeError, ValueError, AttributeError) as e:
            if isinstance(e, ProvenanceFailed) and e.code.startswith(("API_", "RECORDS_")):
                raise
            out["unproven_records"].append(path)
            if isinstance(game, str):
                bad_games.add(game)
    out["captures"] = [c for c in out["captures"] if c["game_id"] not in bad_games]
    out["unproven_games"] = sorted(bad_games)
    return out


def load_settlements(api, game_kickoffs: dict, now) -> dict:
    """Settlements ONLY from settlements/<sha>.json data records whose sha256
    matches a fetch record fetch/<sha>.json (hash-matched like the stats),
    pushed AFTER the final (kickoff + 4 h) of the last covered game and
    BEFORE the review time. Conflicting values refuse (SETTLEMENT_CONFLICT)."""
    merged, used, refused = {}, [], []
    for name in _list(api, "settlements"):
        sha, path = name[:-5], f"{ROOT}/settlements/{name}"
        try:
            dp = prove_record(api, path)
            if _sha_text(dp["content"]) != sha:
                raise ProvenanceFailed("SETTLEMENT_HASH_MISMATCH", path)
            fp = verify_fetch(api, sha, None)
            body = json.loads(dp["content"])
            vals = {(r["game_id"], r["player_id"]): r["td"] for r in body["settlements"]}
            if any(v not in (0, 1) or isinstance(v, bool) for v in vals.values()):
                raise ProvenanceFailed("SETTLEMENT_MALFORMED", path)
            covered = [_t(game_kickoffs[g]) for g, _ in vals if g in game_kickoffs]
            if not covered:
                continue
            push = _t(fp["pushed_at"])
            if push <= max(covered) + FINAL_BUFFER:
                raise ProvenanceFailed("SETTLEMENT_PUSH_BEFORE_FINAL", path)
            if push >= now:
                raise ProvenanceFailed("SETTLEMENT_PUSH_NOT_BEFORE_REVIEW", path)
        except ProvenanceFailed as e:
            if e.code.startswith(("API_", "RECORDS_")):
                raise
            refused.append({"path": path, "code": e.code})
            continue
        except (KeyError, TypeError, ValueError, AttributeError):
            refused.append({"path": path, "code": "SETTLEMENT_MALFORMED"})
            continue
        for k, v in vals.items():
            if k in merged and merged[k] != v:
                raise ProvenanceFailed("SETTLEMENT_CONFLICT", f"{k}")
            merged[k] = v
        used.append({"path": path, "sha256": sha, "fetch_pushed_at": fp["pushed_at"]})
    return {"settlements": merged, "records": used, "refused": refused}
