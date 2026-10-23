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
                      first_kickoff=None, teams_override=None, player_team=None):
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
    # stats data record: real gzip CSV; each player on his game's home team
    # unless player_team overrides ({pid: team}, None = absent from stats)
    import gzip
    pteam = {r["player_id"]: f"H{r['game_id']}" for s_ in ledger for r in s_["rows"]}
    pteam.update(player_team or {})
    lines = ["player_id,season,season_type,week,recent_team"] + [
        f"{p},2026,REG,7,{t}" for p, t in sorted(pteam.items()) if t is not None]
    st = publish_data(api, gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0),
                      "2026-10-25T15:00:00Z", name="stats", ext="csv.gz")
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
        wk = slate["rows"][0]["week"] if slate["rows"] else 8
        board = {"slate_id": slate["slate_id"], "season": 2026, "week": wk,
                 "captured_at": captured_at, "rows": rows}
        bsha = publish_board(api, board, f"2026-10-25T16:0{k % 10}:30Z")
        rec = {"slate_id": slate["slate_id"], "captured_at": captured_at,
               "season": 2026, "week": wk, "pricer_sha256": FAKE_PRICER_SHA,
               "inputs": {"board": bsha, "stats": st, "schedule": sc_, "player_data": {}},
               "game_teams": {r["game_id"]: list((teams_override or {}).get(
                   r["game_id"], games[r["game_id"]][:2])) for r in slate["rows"]},
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


# ---------------------------------------------------------------------------
# Replay (re-audit of 353147d5). Synthetic legacy ledgers cannot be real
# pricer output, so they cite FAKE_PRICER_SHA, whose registered test
# replayer re-derives rows from the pushed board record (still a genuine
# byte-identical check). Real-pricer tests use synthetic_world() below.
FAKE_PRICER_SHA = "f" * 64


def fake_replay(inputs, *, now, fetched_at):
    return json.loads(inputs["board"])["rows"]


def fake_replayers():
    """Stand-in for pv.replayers inside test fixtures only (never registered
    on import): the fake pricer plus the real one."""
    import price_nfl_atd_board_v11 as pr
    return {FAKE_PRICER_SHA: fake_replay, pr.pricer_sha256(): pr.replay}


def module_fixtures(*, guard):
    """(setUpModule, tearDownModule) for a test module that uses the fake
    pricer: patches pv.replayers via unittest.mock.patch.object, and, if
    guard=True, explicitly patches the review environment guard too."""
    from unittest import mock
    patchers = []

    def setup():
        import atd_provenance as pv
        patchers.append(mock.patch.object(pv, "replayers", fake_replayers))
        if guard:
            import score_nfl_atd_forward as sc
            patchers.append(mock.patch.object(sc, "_review_env_guard", lambda: None))
        for p in patchers:
            p.start()

    def teardown():
        while patchers:
            patchers.pop().stop()
    return setup, teardown


def publish_board(api, board: dict, pushed_at):
    """Push a board capture record boards/<season>-W<week>/<sha>.json."""
    import atd_provenance as pv
    body = json.dumps(board, sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    p = pv.board_record_path(sha, board["season"], board["week"])
    if api.get_file(pv.RECORDS_BRANCH, p) is None:
        api.commit(pv.RECORDS_BRANCH, {p: body}, pushed_at)
    return sha


def republish_run(api, rec, slate_id, pushed_at, board_pushed_at=None):
    """Push a hand-edited run record WITH a board record that replays to its
    rows (fake pricer), i.e. an honest record for those rows."""
    import atd_provenance as pv
    rec = dict(rec, slate_id=slate_id)
    b = {"slate_id": slate_id, "season": rec["season"], "week": rec["week"],
         "captured_at": rec["captured_at"], "rows": rec["rows"]}
    from datetime import datetime, timedelta
    before = (datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
              - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["inputs"] = dict(rec["inputs"], board=publish_board(
        api, b, board_pushed_at or before))
    api.commit(pv.RECORDS_BRANCH, {pv.run_record_path(slate_id): json.dumps(rec)}, pushed_at)
    return rec


class synthetic_world:
    """Tiny self-consistent world for the REAL pricer: one pinned player-data
    file (pins patched to it), 2026 stats weeks 1-7 (KC v LV, 40 WRs a side
    + a few named players), schedule incl. week 8, and a week-8 board.
    Use as a context manager (patches eng.REQUIRED_FILES / PART2_HASHES)."""
    CAP, KO = "2026-10-25T16:00:00Z", "2026-10-25T17:00:00Z"

    def __init__(self, board_rows=None):
        import gzip
        import tempfile
        from pathlib import Path
        self.dir = Path(tempfile.mkdtemp())
        hdr = ("player_id,player_display_name,position_group,season,season_type,week,"
               "recent_team,opponent_team,game_id,rushing_tds,receiving_tds,special_teams_tds")
        hist = [hdr]
        for w in range(1, 18):
            for pid, team in (("P1", "KC"), ("P2", "LV"), ("TR", "KC"), ("OLD", "KC")):
                hist.append(f"{pid},{pid} Name,WR,2025,REG,{w},{team},XX,,"
                            f"0,{1 if w % 3 == 0 else 0},0")
        self.player_data = {"ps_2025.csv.gz": gzip.compress(("\n".join(hist) + "\n").encode(), mtime=0)}
        games, cur = [], [hdr]
        for w in range(1, 9):
            home, away = ("KC", "LV") if w % 2 else ("LV", "KC")
            gid = f"2026_{w:02d}_{away}_{home}"
            day = f"2026-{(9 if w <= 3 else 10):02d}-{[0, 7, 14, 21, 28, 5, 12, 19, 25][w]:02d}"
            games.append(f"{gid},2026,REG,{w},{day},Sunday,13:00,{away},{home},"
                         f"{'' if w == 8 else '3'}")
            if w == 8:
                continue
            for team in ("KC", "LV"):
                opp = "LV" if team == "KC" else "KC"
                for i in range(40):
                    cur.append(f"F{team}{i},F{team}{i} Name,WR,2026,REG,{w},{team},{opp},{gid},"
                               f"0,{1 if (i + w) % 4 == 0 else 0},0")
            cur.append(f"P1,P1 Name,WR,2026,REG,{w},KC,LV,{gid},0,{w % 2},0")
            cur.append(f"P2,P2 Name,WR,2026,REG,{w},LV,KC,{gid},0,0,0")
            # TR: tied latest week on two teams (different games) -> unresolved
            cur.append(f"TR,TR Name,WR,2026,REG,{w},KC,LV,{gid},0,0,0")
        cur.append("TR,TR Name,WR,2026,REG,7,DEN,KC,2026_07_KC_LV_X,0,0,0")
        games.append("2026_07_KC_LV_X,2026,REG,7,2026-10-12,Monday,20:15,KC,DEN,7")
        self.stats = gzip.compress(("\n".join(cur) + "\n").encode(), mtime=0)
        self.schedule = ("game_id,season,game_type,week,gameday,weekday,gametime,away_team,"
                         "home_team,result\n" + "\n".join(games) + "\n").encode()
        self.board = {"slate_id": "W1", "season": 2026, "week": 8,
                      "game_id": "board-kc-lv", "game_teams": ["KC", "LV"],
                      "kickoff": self.KO, "captured_at": self.CAP,
                      "rows": board_rows or [
                          {"player_id": "P1", "player_name": "P1 Name", "yes_price": 250},
                          {"player_id": "P2", "player_name": "P2 Name", "yes_price": 400},
                          {"player_id": "OLD", "player_name": "OLD Name", "yes_price": 300},
                          {"player_id": "TR", "player_name": "TR Name", "yes_price": 300},
                          {"player_id": "ZZ", "player_name": "Nobody", "yes_price": 300}]}

    def __enter__(self):
        import atd_engine as eng
        pf = self.dir / "SPEC_HASHES.txt"
        pf.write_text("".join(f"{hashlib.sha256(b).hexdigest()} {n}\n"
                              for n, b in self.player_data.items()))
        self._saved = (eng.REQUIRED_FILES, eng.PART2_HASHES)
        eng.REQUIRED_FILES, eng.PART2_HASHES = tuple(self.player_data), pf
        return self

    def __exit__(self, *a):
        import atd_engine as eng
        eng.REQUIRED_FILES, eng.PART2_HASHES = self._saved

    def inputs(self):
        return {"board": json.dumps(self.board, sort_keys=True).encode(),
                "stats": self.stats, "schedule": self.schedule,
                "player_data": dict(self.player_data)}

    def publish(self, api, rows, *, pricer_sha=None, run_at="2026-10-25T16:30:00Z",
                board_at="2026-10-25T16:10:00Z", skip=(), edit=None):
        """Push data/fetch/board records then a run record carrying `rows`."""
        import atd_provenance as pv
        import price_nfl_atd_board_v11 as pr
        br = pv.RECORDS_BRANCH
        st = publish_data(api, self.stats, "2026-10-25T15:00:00Z", "stats", "csv.gz")
        sc = publish_data(api, self.schedule.decode(), "2026-10-25T15:01:00Z")
        pins = {}
        for n, b in self.player_data.items():
            sha = hashlib.sha256(b).hexdigest()
            pins[n] = sha
            if "player_data" not in skip:
                api.commit(br, {pv.data_record_path(sha, "csv.gz"): b}, "2026-10-25T15:02:00Z")
        bsha = hashlib.sha256(self.inputs()["board"]).hexdigest()
        if "board" not in skip:
            api.commit(br, {pv.board_record_path(bsha, 2026, 8): self.inputs()["board"].decode()},
                       board_at)
        ev = {s: next(e for e in api.events
                      if e["after"] == api.file_commits(br, pv.fetch_record_path(s))[0])
              for s in (st, sc)}
        rows = json.loads(json.dumps(rows))
        if edit:
            edit(rows)
        gid = next((r["game_id"] for r in rows if r.get("game_id")), "2026_08_LV_KC")
        rec = {"slate_id": "W1", "captured_at": self.CAP, "season": 2026, "week": 8,
               "first_kickoff": self.KO, "game_teams": {gid: ["KC", "LV"]},
               "schedule_kickoffs": {gid: self.KO},
               "stats_sha256": st, "schedule_sha256": sc,
               "pricer_sha256": pricer_sha or pr.pricer_sha256(),
               "inputs": {"board": bsha, "stats": st, "schedule": sc, "player_data": pins},
               "fetch_provenance": {"stats": {"event": ev[st]}, "schedule": {"event": ev[sc]}},
               "rows": rows}
        api.commit(br, {pv.run_record_path("W1"): json.dumps(rec, sort_keys=True)}, run_at)
        return rec

