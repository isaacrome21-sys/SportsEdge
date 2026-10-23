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


ZERO = "0" * 40


class FakeGitHub:
    """init_records=True creates the records branch with a dummy first
    commit (a branch_creation event, as GitHub reports it), so records are
    always later pushes. page_size models activity pagination."""
    def __init__(self, init_records=True, page_size=2, authenticated=True):
        self.trees = {"root": {}}
        self.parents = {"root": []}
        self.heads = {}
        self.events = []
        self.malformed = set()   # method names returning junk
        self.page_size = page_size
        self.authenticated = authenticated
        self.truncated = False
        if init_records:
            import atd_provenance as pv
            self.commit(pv.RECORDS_BRANCH, {"README.md": "records branch (dummy first commit)\n"},
                        "2026-10-01T00:00:00Z")

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
        new_branch = branch not in self.heads
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
            if new_branch:
                self.push_event(branch, ZERO, sha, pushed_at, kind="branch_creation")
            else:
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
        c = self.trees.get(self._ref(ref), {}).get(path)
        return c.decode("utf-8", "replace") if isinstance(c, bytes) else c

    def blob_sha(self, ref, path):
        c = self.trees.get(self._ref(ref), {}).get(path)
        if c is None:
            return None
        return hashlib.sha1(c if isinstance(c, bytes) else c.encode()).hexdigest()

    def get_file_bytes(self, ref, path):
        """Raw bytes via the git blobs API (no 1 MB contents limit)."""
        if "get_file_bytes" in self.malformed:
            return "not bytes"
        c = self.trees.get(self._ref(ref), {}).get(path)
        return None if c is None else (c if isinstance(c, bytes) else c.encode())

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

    def git_tree(self, ref):
        """GET /git/trees/{ref}?recursive=1 shape."""
        if "git_tree" in self.malformed:
            return {"tree": "junk"}
        files = self.trees.get(self._ref(ref), {})
        return {"truncated": self.truncated,
                "tree": [{"path": p, "type": "blob"} for p in sorted(files)]}

    def activity_page(self, branch, cursor=None):
        """One page of GET /activity (newest first); returns (items, next)."""
        if "activities" in self.malformed or "activity_page" in self.malformed:
            return [{"oops": 1}], None
        evs = [e for e in reversed(self.events) if e["ref"] == f"refs/heads/{branch}"]
        i = cursor or 0
        nxt = i + self.page_size
        return [dict(e) for e in evs[i:nxt]], (nxt if nxt < len(evs) else None)

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


def publish_data(api, body, pushed_at, name="schedule", ext="csv"):
    """Push a hash-named data record data/<sha>.<ext> (single commit) and its
    fetch record fetch/<sha>.json; idempotent per sha. Returns sha."""
    import atd_provenance as pv
    raw = body.encode() if isinstance(body, str) else body
    sha = hashlib.sha256(raw).hexdigest()
    br = pv.RECORDS_BRANCH
    if api.get_file_bytes(br, pv.data_record_path(sha, ext)) is None:
        api.commit(br, {pv.data_record_path(sha, ext): body}, pushed_at)
        api.commit(br, {pv.fetch_record_path(sha): json.dumps({"sha256": sha, "kind": name})},
                   pushed_at)
    return sha


def schedule_csv(games):
    """nflverse games.csv rows for {game_id: (away, home, week, kickoff_iso)}."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    lines = ["game_id,season,game_type,week,gameday,weekday,gametime,away_team,home_team,result"]
    for g, (away, home, week, ko) in sorted(games.items()):
        et = datetime.fromisoformat(ko.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        lines.append(f"{g},2026,REG,{week},{et:%Y-%m-%d},Sunday,{et:%H:%M},{away},{home},")
    return "\n".join(lines) + "\n"


def ledger_to_records(api, ledger, captured_at="2026-10-25T16:00:00Z",
                      kickoff="2026-10-25T17:00:00Z", schedule_ko=None,
                      first_kickoff=None):
    """Publish a pre-scored test ledger as pushed data + fetch + run records,
    and derive the captures/settlements that reproduce each row's clv/outcome.
    Rows claim `kickoff`; the pushed schedule says `schedule_ko` (default:
    the same), so a forged run record can be modelled."""
    import atd_provenance as pv
    br = pv.RECORDS_BRANCH
    games = {}
    for s_ in ledger:
        for r in s_["rows"]:
            games[r["game_id"]] = (f"A{r['game_id']}", f"H{r['game_id']}", r["week"],
                                   schedule_ko or kickoff)
    st = publish_data(api, b"\x1f\x8b fake stats gz bytes", "2026-10-25T15:00:00Z",
                      name="stats", ext="csv.gz")
    sc_ = publish_data(api, schedule_csv(games), "2026-10-25T15:01:00Z")
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
               "season": 2026,
               "game_teams": {r["game_id"]: list(games[r["game_id"]][:2]) for r in slate["rows"]},
               "schedule_kickoffs": {r["game_id"]: kickoff for r in slate["rows"]},
               "first_kickoff": first_kickoff or kickoff,
               "stats_sha256": st, "schedule_sha256": sc_,
               "fetch_provenance": {"stats": {"event": events[st]},
                                    "schedule": {"event": events[sc_]}},
               "rows": rows}
        api.commit(br, {pv.run_record_path(slate["slate_id"]): json.dumps(rec, sort_keys=True)},
                   f"2026-10-25T16:{10 + k % 40:02d}:00Z")
        ids.append(slate["slate_id"])
    return ids, captures, settlements


def publish_close(api, game_id, kickoff, captured_at, captures, pushed_at,
                  season=2026, week=8, raw=None):
    """Push one close-capture file as its own record
    closes/<season>-W<week>/<sha256>.json (raw: exact body to publish)."""
    import atd_provenance as pv
    body = raw if raw is not None else json.dumps(
        {"game_id": game_id, "kickoff": kickoff, "captured_at": captured_at,
         "captures": captures}, sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    api.commit(pv.RECORDS_BRANCH, {pv.close_record_path(sha, season, week): body}, pushed_at)
    return sha


def publish_settlements(api, settlements, pushed_at, data_pushed_at=None,
                        season=2026, week=8, rows=None):
    """Push a settlement data file (settlements/<season>-W<week>/<sha>.json)
    and its fetch record (fetch/<sha>.json); returns the sha. `rows` gives
    the raw settlement list (e.g. with duplicate keys)."""
    import atd_provenance as pv
    rows = rows if rows is not None else [
        {"game_id": g, "player_id": p, "td": v} for (g, p), v in sorted(settlements.items())]
    body = json.dumps({"settlements": rows}, sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    api.commit(pv.RECORDS_BRANCH, {pv.settlement_data_path(sha, season, week): body},
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
    week_of = {r["game_id"]: r["week"] for s in ledger for r in s["rows"]}
    by_game = {}
    for c in caps:
        by_game.setdefault(c["game_id"], []).append(
            {"player_id": c["player_id"], "yes_price": c["yes_price"],
             "captured_at": c["captured_at"]})
    for g, cs in sorted(by_game.items()):
        publish_close(api, g, "2026-10-25T17:00:00Z", "2026-10-25T16:30:00Z", cs,
                      close_pushed, week=week_of[g])
    by_week = {}
    for (g, p), v in setl.items():
        by_week.setdefault(week_of[g], {})[(g, p)] = v
    for w, part in sorted(by_week.items()):
        publish_settlements(api, part, settle_pushed, week=w)
    return ids
