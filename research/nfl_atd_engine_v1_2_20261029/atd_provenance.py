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


def data_record_path(sha256: str, ext: str = "csv") -> str:
    """Hash-named data record (schedule .csv, stats .csv.gz)."""
    return f"{ROOT}/data/{sha256}.{ext}"


FREEZE_PATH = f"{ROOT}/FREEZE.json"
FREEZE_KEYS = ("pricer_sha256", "scorer_sha256", "provenance_sha256", "prereg_sha256")


def load_freeze(api, stored_event=None) -> dict:
    """The FREEZE pins: a single-commit record on the records branch (never
    hardcoded in code, so no self-hash loop). Returns the pins + pushed_at."""
    try:
        p = prove_record(api, FREEZE_PATH, stored_event)
    except ProvenanceFailed as e:
        code = e.code if e.code.startswith(("API_", "RECORDS_")) else \
            "FREEZE_" + e.code.replace("RECORD_", "", 1)
        raise ProvenanceFailed(code, e.detail)
    try:
        body = json.loads(p["content"])
        out = {k: body[k] for k in FREEZE_KEYS}
        if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in out.values()):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ProvenanceFailed("FREEZE_MALFORMED", FREEZE_PATH)
    return dict(out, pushed_at=p["pushed_at"], commit=p["commit"], event=p["event"])


def board_record_path(sha256: str, season, week) -> str:
    """Board capture record (pricer input), filed under its season-week."""
    return f"{ROOT}/boards/{int(season)}-W{int(week)}/{sha256}.json"


def canonical_json(obj) -> bytes:
    """Canonical JSON for the replay comparison."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def replayers() -> dict:
    """The only replayer: the pricer whose code hashes to pricer_sha256()."""
    import price_nfl_atd_board_v11 as pr
    return {pr.pricer_sha256(): pr.replay}


_ORIGINAL_REPLAYERS = replayers     # identity checked by the review guard


DATA_EXT = {"schedule": "csv", "stats": "csv.gz"}


def week_dir(season, week) -> str:
    return f"{int(season)}-W{int(week)}"


def close_record_path(sha256: str, season, week) -> str:
    return f"{ROOT}/closes/{week_dir(season, week)}/{sha256}.json"


def settlement_data_path(sha256: str, season, week) -> str:
    return f"{ROOT}/settlements/{week_dir(season, week)}/{sha256}.json"


def require_token(api):
    """Review and pricing need an authenticated client (rule 5)."""
    if not getattr(api, "authenticated", False):
        raise ProvenanceFailed("GITHUB_TOKEN_MISSING", "set GITHUB_TOKEN")


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
        tok = token if token is not None else os.environ.get("GITHUB_TOKEN")
        if not tok:
            raise ProvenanceFailed("GITHUB_TOKEN_MISSING", "set GITHUB_TOKEN")
        self._token = tok           # never printed, logged or recorded
        self.authenticated = True

    def __repr__(self):
        return f"GitHubAPI({self.base}, token=<redacted>)"

    @property
    def token(self):
        return self._token

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

    def get_file_bytes(self, ref, path):
        """Raw bytes via the git blobs API (contents API caps at 1 MB)."""
        js = self._contents(ref, path)
        if js is None:
            return None
        b, _ = self._req(f"{self.base}/git/blobs/{js['sha']}")
        return None if b is None else base64.b64decode(b["content"])

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

    def git_tree(self, ref):
        """GET /git/trees/{tree}?recursive=1 for the ref's head commit."""
        c, _ = self._req(f"{self.base}/commits/{quote(ref, safe='')}")
        if c is None:
            return {"truncated": False, "tree": []}
        js, _ = self._req(f"{self.base}/git/trees/{c['commit']['tree']['sha']}?recursive=1")
        return js

    def activity_page(self, branch, cursor=None):
        """One page of the activity API; cursor = next-page URL (Link)."""
        url = cursor or (f"{self.base}/activity?ref={quote('refs/heads/' + branch, safe='')}"
                         f"&per_page=100")
        js, h = self._req(url)
        m = re.search(r'<([^>]+)>;\s*rel="next"', (h or {}).get("Link") or "")
        return js or [], (m.group(1) if m else None)

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


MAX_ACTIVITY_PAGES = 10000


def _events(api):
    """Every activity event for the records branch, following pagination."""
    evs, cursor = [], None
    for _ in range(MAX_ACTIVITY_PAGES):
        page = _call(api.activity_page, RECORDS_BRANCH, cursor)
        if not (isinstance(page, tuple) and len(page) == 2 and isinstance(page[0], list)):
            raise ProvenanceFailed("API_MALFORMED", "activity page")
        evs += page[0]
        cursor = page[1]
        if cursor is None:
            break
    else:
        raise ProvenanceFailed("API_MALFORMED", "activity pagination did not end")
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


def prove_record(api, path, stored_event=None, binary=False) -> dict:
    """Prove a record's single commit and its server push time (rules A, F, G).
    binary=True reads the head as bytes via the blobs API (data records)."""
    events = _events(api)                           # refuses rewrites first
    commits = _call(api.file_commits, RECORDS_BRANCH, path)
    if not isinstance(commits, list) or not all(isinstance(c, str) for c in commits):
        raise ProvenanceFailed("API_MALFORMED", "file_commits")
    head = _call(api.get_file_bytes if binary else api.get_file, RECORDS_BRANCH, path)
    if head is not None and not isinstance(head, bytes if binary else str):
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
    if any(e["after"] == c and e["activity_type"] == "branch_creation" for e in events) or (
            isinstance(stored_event, dict) and stored_event.get("after") == c
            and stored_event.get("activity_type") == "branch_creation"):
        raise ProvenanceFailed("RECORD_IN_BRANCH_CREATION",
                               f"{path}: branch_creation push carries no provable push")
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


def load_data_record(api, sha256, ext="csv", stored_event=None, fetch_event=None,
                     require_fetch=True):
    """A hash-named single-commit data record data/<sha>.<ext> whose bytes
    hash to sha256, matched to fetch/<sha>.json (as settlements are).
    Returns the data proof with 'bytes' and 'fetch' (fetch-record proof)."""
    path = data_record_path(sha256, ext)
    try:
        p = prove_record(api, path, stored_event, binary=True)
    except ProvenanceFailed as e:
        code = e.code if e.code.startswith(("API_", "RECORDS_")) else "DATA_" + e.code
        raise ProvenanceFailed(code, e.detail)
    if hashlib.sha256(p["content"]).hexdigest() != sha256:
        raise ProvenanceFailed("DATA_RECORD_HASH_MISMATCH", path)
    p["fetch"] = verify_fetch(api, sha256, None, fetch_event) if require_fetch else None
    p["bytes"] = p.pop("content")
    return p


def stats_teams(gz_bytes, season) -> dict:
    """{player_id: team} from the pinned stats data record: the team on the
    player's latest REG week of `season`."""
    import csv
    import gzip
    import io
    best = {}
    for r in csv.DictReader(io.StringIO(gzip.decompress(gz_bytes).decode())):
        if r.get("season_type") != "REG" or int(r["season"]) != int(season):
            continue
        w = int(r["week"])
        team = r.get("recent_team") or r.get("team") or ""
        cur = best.get(r["player_id"])
        if cur is None or w > cur[0]:
            best[r["player_id"]] = (w, team)
        elif w == cur[0] and cur[1] != team:
            best[r["player_id"]] = (w, None)    # same-week tie, different teams
    return {p: t for p, (w, t) in best.items()}


def require_fetch_provenance(api, shas: dict, captured_at) -> dict:
    """Pricer gate: each input needs its data record AND fetch record on the
    branch, both pushed before capture. Returns proofs (events to store)."""
    require_token(api)
    out = {}
    for name, sha in shas.items():
        d = load_data_record(api, sha, DATA_EXT.get(name, "csv"))
        f = d.pop("fetch")
        d.pop("bytes")
        if captured_at is not None and max(_t(d["pushed_at"]), _t(f["pushed_at"])) >= _t(captured_at):
            raise ProvenanceFailed("DATA_PUSH_NOT_BEFORE_CAPTURE", name)
        out[name] = dict(f, data_event=d["event"], data_pushed_at=d["pushed_at"])
    return out


def load_slate(api, slate_id, now=None) -> dict:
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
    if now is not None and _t(rp["pushed_at"]) > now:
        out["reasons"].append("RUN_RECORD_NOT_ON_BRANCH")   # not yet pushed as of now
        return out
    out["run_proof"] = {k: v for k, v in rp.items() if k != "content"}
    out["content"] = rp["content"]
    try:
        rec = json.loads(rp["content"])
        cap, ko = _t(rec["captured_at"]), _t(rec["first_kickoff"])
        shas = {"stats": rec["stats_sha256"], "schedule": rec["schedule_sha256"]}
        stored = rec.get("fetch_provenance")
        if stored is None:
            stored = {}
        if not isinstance(stored, dict) or any(
                name in stored and not isinstance(stored[name], dict)
                for name in ("stats", "schedule", "freeze", "board")):
            raise ValueError("fetch_provenance entries must be objects")
        rows = rec["rows"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("run rows must be an array of objects")
        for row in rows:
            if row.get("status") == "UNPRICED":
                reason = row.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError("unpriced refusal reason must be a nonempty string")
        season = rec["season"]
        if type(season) is not int or season < 1:
            raise ValueError("run season must be a positive integer (not bool)")
        run_week = rec["week"]
        if type(run_week) is not int or run_week < 1:
            raise ValueError("run week must be a positive integer (not bool)")
        teams = rec["game_teams"]
        if rec.get("slate_id") != slate_id or not isinstance(rows, list) \
                or not isinstance(teams, dict):
            raise ValueError("slate_id/rows/game_teams")
        priced = [r for r in rows if r.get("status") == "PRICED"]
        # A zero-priced slate has no independently schedule-bound candidate.
        # It must not start a counted clock merely because replay matches.
        if not priced:
            out["reasons"].append("RUN_NO_PRICED_ROWS")
        for r in priced:
            _t(r["kickoff"]), r["game_id"]
        # the run-record field schedule_kickoffs is informational only
    except (ValueError, KeyError, TypeError):
        out["reasons"].append("RUN_RECORD_MALFORMED")
        return out
    # kickoffs are recomputed from the pushed schedule data record, never
    # taken from the run record (ruling 87236180)
    kos = {}
    sch = None
    try:
        ev = (stored.get("schedule") or {}) if isinstance(stored, dict) else {}
        sch = load_data_record(api, shas["schedule"], "csv", ev.get("data_event"), ev.get("event"))
    except ProvenanceFailed as e:
        out["reasons"].append(e.code)
    pteams, sd = None, None
    try:
        ev = (stored.get("stats") or {}) if isinstance(stored, dict) else {}
        sd = load_data_record(api, shas["stats"], DATA_EXT["stats"],
                              ev.get("data_event"), ev.get("event"))
        pteams = stats_teams(sd["bytes"], season)
    except ProvenanceFailed as e:
        out["reasons"].append(e.code)
    except (OSError, ValueError, KeyError, EOFError):
        out["reasons"].append("DATA_RECORD_MALFORMED")
    if sch is not None:
        import tempfile
        import atd_refresh as rf
        with tempfile.NamedTemporaryFile(suffix=".csv") as fh:
            fh.write(sch["bytes"])
            fh.flush()
            for r in priced:
                try:
                    k = rf.schedule_kickoff(fh.name, season, teams.get(r["game_id"]), r["kickoff"])
                    # A real priced row omits week. Bind the independently
                    # pinned schedule week to the run/board metadata anyway;
                    # replay alone only proves the latter two agree.
                    if type(k["week"]) is not int or k["week"] != run_week:
                        raise rf.RefreshFailed("KICKOFF_SCHEDULE_MISMATCH", r["game_id"])
                    if "week" in r and (type(r["week"]) is not int or r["week"] != k["week"]):
                        raise rf.RefreshFailed("KICKOFF_SCHEDULE_MISMATCH", r["game_id"])
                    if k["game_id"] != r["game_id"]:
                        out["reasons"].append("ROW_GAME_ID_MISMATCH")
                        continue
                    if pteams is not None and pteams.get(r.get("player_id")) \
                            not in set(teams.get(r["game_id"]) or []):
                        out["reasons"].append("ROW_PLAYER_TEAM_MISMATCH")
                    if kos.setdefault(r["game_id"], k["kickoff"]) != k["kickoff"]:
                        raise rf.RefreshFailed("KICKOFF_SCHEDULE_MISMATCH", r["game_id"])
                except (rf.RefreshFailed, ValueError, KeyError, TypeError):
                    out["reasons"].append("ROW_KICKOFF_SCHEDULE_MISMATCH")
        if kos and not {"ROW_KICKOFF_SCHEDULE_MISMATCH", "ROW_GAME_ID_MISMATCH"} & set(out["reasons"]):
            earliest = min(_t(v) for v in kos.values())
            if earliest != ko:
                out["reasons"].append("FIRST_KICKOFF_MISMATCH")
            ko = earliest
        out["schedule_data_proof"] = {k: v for k, v in sch.items() if k not in ("bytes", "fetch")}
    out["kickoffs"] = kos
    refs = {}
    for r in rows:
        if isinstance(r, dict) and r.get("status") == "UNPRICED":
            refs[r.get("reason")] = refs.get(r.get("reason"), 0) + 1
    out["refusals"] = refs
    import atd_engine as eng
    import price_nfl_atd_board_v11 as pr
    declared = set(eng.DECLARED_UNPRICED_REASONS) | set(pr.DECLARED_PRICER_REFUSALS)
    if any(k not in declared for k in refs):
        out["reasons"].append("RUN_REFUSAL_CODE_UNDECLARED")
    run_t = _t(rp["pushed_at"])
    try:
        fpv = rec.get("fetch_provenance") if isinstance(rec.get("fetch_provenance"), dict) else {}
        fev = (fpv.get("freeze") or {}).get("event") if isinstance(fpv.get("freeze"), dict) else None
        fz = load_freeze(api, fev)
        if run_t <= _t(fz["pushed_at"]):
            out["reasons"].append("RUN_PUSH_NOT_AFTER_FREEZE")
    except ProvenanceFailed as e:
        out["reasons"].append(e.code)
    if run_t < cap:
        out["reasons"].append("RUN_PUSH_BEFORE_CAPTURE")
    if run_t >= ko:
        out["reasons"].append("RUN_PUSH_NOT_BEFORE_KICKOFF")
    for name, sha in shas.items():
        ev = (stored.get(name) or {}).get("event") if isinstance(stored, dict) else None
        try:
            fp = verify_fetch(api, sha, None, ev)
            if name == "stats":     # schedule data record already loaded above
                dp = load_data_record(api, sha, DATA_EXT[name],
                                      (stored.get(name) or {}).get("data_event"), ev)
                if _t(dp["pushed_at"]) >= cap:
                    out["reasons"].append("DATA_PUSH_NOT_BEFORE_CAPTURE")
            elif sch is not None and _t(sch["pushed_at"]) >= cap:
                out["reasons"].append("DATA_PUSH_NOT_BEFORE_CAPTURE")
            ft = _t(fp["pushed_at"])
            if ft >= cap:
                out["reasons"].append("FETCH_PUSH_NOT_BEFORE_CAPTURE")
            if ft >= run_t:
                out["reasons"].append("FETCH_PUSH_NOT_BEFORE_RUN_PUSH")
            out[f"{name}_fetch_proof"] = fp
        except ProvenanceFailed as e:
            out["reasons"].append(e.code)
    _replay_check(api, rec, rows, run_t, sch, sd, out)
    out["record"] = rec
    out["season"] = season
    out["reasons"] = sorted(set(out["reasons"]))
    out["status"] = "SCREEN" if out["reasons"] else "COUNTS"
    return out


def _replay_check(api, rec, rows, run_t, sch, sd, out):
    """Full replay (re-audit of 353147d5): load every pricer input from its
    single-commit branch record (each pushed before the run record), re-run
    the sha-verified pricer on exactly those bytes with injected time (the
    run push) and require canonical-JSON-identical rows."""
    try:
        inp = rec["inputs"]
        psha = rec["pricer_sha256"]
        week = int(rec["week"])
        pins = inp["player_data"]
        if not isinstance(pins, dict) or inp["stats"] != rec["stats_sha256"] \
                or inp["schedule"] != rec["schedule_sha256"]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        out["reasons"].append("RUN_RECORD_MALFORMED")
        return
    stored = rec.get("fetch_provenance") if isinstance(rec.get("fetch_provenance"), dict) else {}
    bev = (stored.get("board") or {}).get("event") if isinstance(stored.get("board"), dict) else None
    pdev = stored.get("player_data") if isinstance(stored.get("player_data"), dict) else {}
    reg = replayers()
    if psha not in reg:
        out["reasons"].append("RUN_PRICER_SHA_MISMATCH")
        return
    ok = sch is not None and sd is not None
    for p in (sch, sd):
        if p is not None and _t(p["pushed_at"]) >= run_t:
            out["reasons"].append("INPUT_PUSH_NOT_BEFORE_RUN_PUSH")
    board = None
    bpath = board_record_path(str(inp["board"]), rec["season"], week)
    try:
        bp = prove_record(api, bpath, bev)
        if _sha_text(bp["content"]) != inp["board"]:
            raise ProvenanceFailed("RECORD_HASH_MISMATCH", bpath)
        if _t(bp["pushed_at"]) >= run_t:
            out["reasons"].append("INPUT_PUSH_NOT_BEFORE_RUN_PUSH")
        board = json.loads(bp["content"])
        # Do not let Python int-coercion or stringification disguise a
        # board week whose type differs from the exact run/schedule week.
        if type(board.get("season")) is not int or board["season"] != rec["season"] \
                or type(board.get("week")) is not int or board["week"] != rec["week"] \
                or any(str(board.get(k)) != str(rec.get(k))
                       for k in ("slate_id", "captured_at")):
            out["reasons"].append("RUN_BOARD_MISMATCH")
        out["board_proof"] = {k: v for k, v in bp.items() if k != "content"}
    except ProvenanceFailed as e:
        out["reasons"].append(e.code if e.code.startswith(("API_", "RECORDS_"))
                              else "BOARD_" + e.code)
        ok = False
    except (ValueError, AttributeError):
        out["reasons"].append("RUN_BOARD_MISMATCH")
        ok = False
    pd = {}
    for name, sha in sorted(pins.items()):
        try:
            d = load_data_record(api, sha, "csv.gz", (pdev.get(name) or {}).get("event")
                                 if isinstance(pdev.get(name), dict) else None,
                                 require_fetch=False)
            if _t(d["pushed_at"]) >= run_t:
                out["reasons"].append("INPUT_PUSH_NOT_BEFORE_RUN_PUSH")
            pd[name] = d["bytes"]
        except ProvenanceFailed as e:
            out["reasons"].append(e.code)
            ok = False
    if not ok:
        return
    try:
        got = reg[psha]({"board": bp["content"].encode(), "stats": sd["bytes"],
                         "schedule": sch["bytes"], "player_data": pd},
                        now=run_t, fetched_at={"stats": sd["pushed_at"],
                                               "schedule": sch["pushed_at"]})
        same = canonical_json(got) == canonical_json(rows)
    except Exception:                       # replay failed closed -> differs
        same = False
    if not same:
        out["reasons"].append("RUN_REPLAY_MISMATCH")


def _tree_paths(api, sub):
    """Record paths under ROOT/sub via the git trees API; refuse truncation."""
    js = _call(api.git_tree, RECORDS_BRANCH)
    if not isinstance(js, dict) or not isinstance(js.get("tree"), list):
        raise ProvenanceFailed("API_MALFORMED", "git tree")
    if js.get("truncated"):
        raise ProvenanceFailed("API_TREE_TRUNCATED", "git tree truncated")
    pre = f"{ROOT}/{sub}/"
    out = []
    for e in js["tree"]:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            raise ProvenanceFailed("API_MALFORMED", "git tree entry")
        if e.get("type") == "blob" and e["path"].startswith(pre):
            rest = e["path"][len(pre):].split("/")
            m = re.fullmatch(r"(\d{4})-W(\d{1,2})", rest[0]) if len(rest) == 2 else None
            if not m or not rest[1].endswith(".json"):
                raise ProvenanceFailed(
                    "CLOSE_RECORD_UNPROVEN" if sub == "closes" else "SETTLEMENT_MISFILED",
                    f"bad record path {e['path']}")
            out.append((e["path"], int(m.group(1)), int(m.group(2)), rest[1][:-5]))
    return sorted(out)


def _sha_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _pushed_after(api, path, now) -> bool:
    """True iff the record's proven push is after `now` (review as-of time):
    such a record is treated as non-existent."""
    if now is None:
        return False
    try:
        return _t(prove_record(api, path)["pushed_at"]) > now
    except ProvenanceFailed as e:
        if e.code.startswith(("API_", "RECORDS_")):
            raise
        return False


def load_closes(api, games: dict, now=None) -> dict:
    """Close captures ONLY from single-commit records
    closes/<season>-W<week>/<sha256>.json. games: {game_id: {kickoff,
    season, week}} from the counted run-record rows (their kickoffs were
    cross-checked against the pinned schedule). Refuses the review
    (CLOSE_RECORD_UNPROVEN) on any record it cannot parse or attribute to a
    game, or filed under the wrong season-week; refuses
    (CLOSE_KICKOFF_CONFLICT) if a record's kickoff differs from the row
    kickoff. A record is proven iff its server push is >= its captured_at,
    <= ROW kickoff + 15 min, and every entry is < kickoff and <= the push.
    Any unproven record marks the whole game unproven."""
    out = {"captures": [], "unproven_games": [], "unproven_records": [],
           "kickoffs": {}, "records": []}
    bad = set()
    for path, season, week, sha in _tree_paths(api, "closes"):
        if _pushed_after(api, path, now):
            continue
        head = _call(api.get_file, RECORDS_BRANCH, path)
        try:
            body = json.loads(head)
            game = body["game_id"]
            if not isinstance(game, str) or not isinstance(body.get("captures"), list):
                raise ValueError
        except (TypeError, ValueError, KeyError, AttributeError):
            raise ProvenanceFailed("CLOSE_RECORD_UNPROVEN", f"unattributable {path}")
        if game not in games:
            continue
        g = games[game]
        if (season, week) != (int(g["season"]), int(g["week"])):
            raise ProvenanceFailed("CLOSE_RECORD_UNPROVEN", f"misfiled {path}")
        ko = _t(g["kickoff"])
        try:
            if _t(body["kickoff"]) != ko:
                raise ProvenanceFailed("CLOSE_KICKOFF_CONFLICT", path)
        except (ValueError, TypeError, KeyError):
            raise ProvenanceFailed("CLOSE_KICKOFF_CONFLICT", f"{path}: kickoff unreadable")
        try:
            p = prove_record(api, path)
            if _sha_text(p["content"]) != sha:
                raise ProvenanceFailed("CLOSE_RECORD_HASH_MISMATCH", path)
            push = _t(p["pushed_at"])
            if push < _t(body["captured_at"]) or push > ko + CLOSE_PUSH_GRACE:
                raise ProvenanceFailed("CLOSE_PUSH_OUTSIDE_WINDOW", path)
            for c in body["captures"]:
                try:
                    ct = _t(c.get("captured_at"))
                except (ValueError, TypeError):
                    continue        # surfaces as CLOSE_TIMESTAMP_INVALID when scored
                if ct >= ko or ct > push:
                    raise ProvenanceFailed("CLOSE_ENTRY_OUTSIDE_WINDOW", path)
        except ProvenanceFailed as e:
            if e.code.startswith(("API_", "RECORDS_")):
                raise
            out["unproven_records"].append({"path": path, "code": e.code})
            bad.add(game)
            continue
        except (KeyError, TypeError, ValueError, AttributeError):
            out["unproven_records"].append({"path": path, "code": "CLOSE_RECORD_MALFORMED"})
            bad.add(game)
            continue
        out["kickoffs"][game] = g["kickoff"]
        out["captures"] += [dict(c, game_id=game) for c in body["captures"]]
        out["records"].append({"path": path, "commit": p["commit"],
                               "pushed_at": p["pushed_at"], "sha256": sha})
    out["captures"] = [c for c in out["captures"] if c["game_id"] not in bad]
    out["unproven_games"] = sorted(bad)
    return out


def load_settlements(api, games: dict, now) -> dict:
    """Settlements ONLY from settlements/<season>-W<week>/<sha>.json data
    records whose sha256 matches a fetch record fetch/<sha>.json. Both the
    data record's push and the fetch record's push must be after the final
    (kickoff + 4 h) of the last covered game and before the review time; the
    covered games must belong to the record's season-week. Duplicate keys in
    one record, or disagreeing records, refuse (SETTLEMENT_CONFLICT)."""
    merged, used, refused = {}, [], []
    for path, season, week, sha in _tree_paths(api, "settlements"):
        if _pushed_after(api, path, now):
            continue                     # non-existent as of now
        try:
            dp = prove_record(api, path)
            if _sha_text(dp["content"]) != sha:
                raise ProvenanceFailed("SETTLEMENT_HASH_MISMATCH", path)
            body = json.loads(dp["content"])
            vals = {}
            for r in body["settlements"]:
                k = (r["game_id"], r["player_id"])
                if k in vals:
                    raise ProvenanceFailed("SETTLEMENT_CONFLICT", f"duplicate {k} in {path}")
                vals[k] = r["td"]
            if any(v not in (0, 1) or isinstance(v, bool) for v in vals.values()):
                raise ProvenanceFailed("SETTLEMENT_MALFORMED", path)
            covered = {g for g, _ in vals if g in games}
            if not covered:
                continue
            if any((int(games[g]["season"]), int(games[g]["week"])) != (season, week)
                   for g in covered):
                raise ProvenanceFailed("SETTLEMENT_MISFILED", path)
            final = max(_t(games[g]["kickoff"]) for g in covered) + FINAL_BUFFER
            if _t(dp["pushed_at"]) <= final:
                raise ProvenanceFailed("SETTLEMENT_DATA_PUSH_BEFORE_FINAL", path)
            fp = verify_fetch(api, sha, None)
            push = _t(fp["pushed_at"])
            if push > now:               # fetch record did not exist as of now
                raise ProvenanceFailed("FETCH_RECORD_NOT_ON_BRANCH", path)
            if push <= final:
                raise ProvenanceFailed("SETTLEMENT_PUSH_BEFORE_FINAL", path)
            if push > now or _t(dp["pushed_at"]) > now:
                raise ProvenanceFailed("SETTLEMENT_PUSH_NOT_BEFORE_REVIEW", path)
        except ProvenanceFailed as e:
            if e.code.startswith(("API_", "RECORDS_")) or e.code == "SETTLEMENT_CONFLICT":
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
        used.append({"path": path, "sha256": sha, "data_pushed_at": dp["pushed_at"],
                     "fetch_pushed_at": fp["pushed_at"]})
    return {"settlements": merged, "records": used, "refused": refused}
