"""Test-only fake of the GitHub REST surface used by atd_provenance
(contents, commits?path=, commits/{sha}, repository activity). Commits form a
linear history per branch; every push emits a server-style activity event."""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import tempfile
from pathlib import Path

_ids = itertools.count(1000)


class FakeGitHub:
    def __init__(self):
        self.trees = {"root": {}}
        self.parents = {"root": []}
        self.heads = {}
        self.events = []
        self.malformed = set()   # method names returning junk

    def _new(self, branch, tree):
        parent = self.heads.get(branch, "root")
        sha = hashlib.sha1(f"{next(_ids)}".encode()).hexdigest()
        self.trees[sha] = tree
        self.parents[sha] = [parent]
        self.heads[branch] = sha
        return sha, parent

    def commit(self, branch, files: dict, pushed_at=None, *, n_commits=1):
        """Commit files (path -> content or None to delete). With pushed_at,
        push the commit(s) as ONE push event (n_commits > 1 = multi-commit push)."""
        start = self.heads.get(branch, "root")
        for i in range(n_commits):
            tree = dict(self.trees[self.heads.get(branch, "root")])
            if i == n_commits - 1:
                for p, c in files.items():
                    if c is None:
                        tree.pop(p, None)
                    else:
                        tree[p] = c
            else:
                tree[f"filler{i}"] = str(i)
            sha, _ = self._new(branch, tree)
        if pushed_at is not None:
            self.push_event(branch, start, sha, pushed_at)
        return sha

    def push_event(self, branch, before, after, ts, kind="push"):
        ev = {"id": next(_ids), "ref": f"refs/heads/{branch}", "before": before,
              "after": after, "timestamp": ts, "activity_type": kind}
        self.events.append(ev)
        return ev

    # --- API surface -------------------------------------------------------
    def _ref(self, ref):
        return self.heads.get(ref, ref)

    def get_file(self, ref, path):
        if "get_file" in self.malformed:
            return 12345
        return self.trees.get(self._ref(ref), {}).get(path)

    def blob_sha(self, ref, path):
        c = self.trees.get(self._ref(ref), {}).get(path)
        return None if c is None else hashlib.sha1(c.encode()).hexdigest()

    def file_commits(self, branch, path):
        if "file_commits" in self.malformed:
            return {"message": "junk"}
        out, sha = [], self.heads.get(branch)
        while sha and sha != "root":
            p = self.parents[sha][0]
            if self.trees[sha].get(path) != self.trees[p].get(path):
                out.append(sha)
            sha = p
        return out

    def list_dir(self, ref, path):
        if "list_dir" in self.malformed:
            return "junk"
        pre = path.rstrip("/") + "/"
        return sorted({p[len(pre):].split("/")[0]
                       for p in self.trees.get(self._ref(ref), {}) if p.startswith(pre)})

    def commit_info(self, sha):
        if sha not in self.parents:
            return None
        return {"sha": sha, "parents": [{"sha": p} for p in self.parents[sha]]}

    def activities(self, branch):
        if "activities" in self.malformed:
            return [{"oops": 1}]
        return [e for e in self.events if e["ref"] == f"refs/heads/{branch}"]


def records_worktree(origin_url="https://github.com/isaacrome21-sys/SportsEdge.git"):
    """Local git checkout on the records branch whose origin URL is the real
    repo (never contacted: verdict existence is checked via the injected API)."""
    import atd_provenance as pv
    t = Path(tempfile.mkdtemp())
    g = lambda *a: subprocess.run(["git", *a], cwd=t, check=True, capture_output=True)
    g("init", "-q", "-b", pv.RECORDS_BRANCH, ".")
    g("remote", "add", "origin", origin_url)
    return t


def ledger_to_records(api, ledger, captured_at="2026-10-25T16:00:00Z",
                      kickoff="2026-10-25T17:00:00Z"):
    """Publish a pre-scored test ledger as pushed fetch + run records, and
    derive the captures/settlements that reproduce each row's clv/outcome."""
    import atd_provenance as pv
    br = pv.RECORDS_BRANCH
    st, sc_ = "a" * 64, "b" * 64
    if api.get_file(br, pv.fetch_record_path(st)) is None:
        for s, t in ((st, "2026-10-25T15:00:00Z"), (sc_, "2026-10-25T15:01:00Z")):
            api.commit(br, {pv.fetch_record_path(s): json.dumps({"sha256": s})}, t)
    events = {s: next(e for e in api.events
                      if e["after"] == api.file_commits(br, pv.fetch_record_path(s))[0])
              for s in (st, sc_)}
    captures, settlements, ids = [], {}, []
    for k, slate in enumerate(ledger):
        rows = []
        for r in slate["rows"]:
            e = {"status": "PRICED", "player_id": r["player_id"],
                 "selection": r["selection"], "game_id": r["game_id"],
                 "week": r["week"], "kickoff": kickoff,
                 "raw_implied": r["raw_implied"]}
            rows.append(e)
            if r.get("clv_status") == "OK":
                q = r["raw_implied"] + r["clv"]
                price = -100 * q / (1 - q) if q >= 0.5 else 100 * (1 - q) / q
                captures.append({"game_id": r["game_id"], "player_id": r["player_id"],
                                 "yes_price": price, "captured_at": "2026-10-25T16:30:00Z"})
            if r.get("outcome_status") == "SETTLED":
                settlements[(r["game_id"], r["player_id"])] = r["outcome"]
        rec = {"slate_id": slate["slate_id"], "captured_at": captured_at,
               "first_kickoff": kickoff, "stats_sha256": st, "schedule_sha256": sc_,
               "fetch_provenance": {"stats": {"event": events[st]},
                                    "schedule": {"event": events[sc_]}},
               "rows": rows}
        api.commit(br, {pv.run_record_path(slate["slate_id"]): json.dumps(rec, sort_keys=True)},
                   f"2026-10-25T16:{10 + k % 40:02d}:00Z")
        ids.append(slate["slate_id"])
    return ids, captures, settlements


def publish_close(api, game_id, kickoff, captured_at, captures, pushed_at):
    """Push one close-capture file as its own record closes/<sha256>.json."""
    import atd_provenance as pv
    body = json.dumps({"game_id": game_id, "kickoff": kickoff,
                       "captured_at": captured_at, "captures": captures},
                      sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    api.commit(pv.RECORDS_BRANCH, {pv.close_record_path(sha): body}, pushed_at)
    return sha


def publish_settlements(api, settlements, pushed_at, data_pushed_at=None):
    """Push a settlement data file (settlements/<sha>.json) and its fetch
    record (fetch/<sha>.json); returns the sha."""
    import atd_provenance as pv
    body = json.dumps({"settlements": [
        {"game_id": g, "player_id": p, "td": v}
        for (g, p), v in sorted(settlements.items())]}, sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    api.commit(pv.RECORDS_BRANCH, {pv.settlement_data_path(sha): body},
               data_pushed_at or pushed_at)
    api.commit(pv.RECORDS_BRANCH,
               {pv.fetch_record_path(sha): json.dumps({"sha256": sha, "kind": "settlements"})},
               pushed_at)
    return sha


def ledger_to_branch(api, ledger, close_pushed="2026-10-25T16:58:00Z",
                     settle_pushed="2026-10-26T12:00:00Z"):
    """ledger_to_records + publish the derived closes (one record per game)
    and settlements on the branch, so review reads nothing from the caller."""
    ids, caps, setl = ledger_to_records(api, ledger)
    by_game = {}
    for c in caps:
        by_game.setdefault(c["game_id"], []).append(
            {"player_id": c["player_id"], "yes_price": c["yes_price"],
             "captured_at": c["captured_at"]})
    for g, cs in sorted(by_game.items()):
        publish_close(api, g, "2026-10-25T17:00:00Z", "2026-10-25T16:30:00Z", cs,
                      close_pushed)
    if setl:
        publish_settlements(api, setl, settle_pushed)
    return ids
