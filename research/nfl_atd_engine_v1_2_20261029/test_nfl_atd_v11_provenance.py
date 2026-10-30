"""v1.1 provenance (re-audit of 9105b4e6, rulings A-G). RED first: these
assert behaviour.  Run: python3 -m unittest test_nfl_atd_v11_provenance -v
"""
import json
import tempfile
import unittest
from pathlib import Path

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import FakeGitHub, ledger_to_branch, records_worktree, publish_data
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
SHA, SSHA = "a" * 64, "b" * 64
CAP = "2026-10-25T16:00:00Z"
KO = "2026-10-25T17:00:00Z"


def fetch(api, sha, t="2026-10-25T15:00:00Z", **kw):
    return api.commit(BR, {pv.fetch_record_path(sha): json.dumps({"sha256": sha})}, t, **kw)


def ev_for(api, commit):
    return next(e for e in api.events if e["after"] == commit)


# Ported (re-audit of 87236180): slates now need real hash-named data
# records; TestFetchAndSlateC publishes them and passes their shas here.
# (port, re-audit 5150203a: load_slate now parses the stats record, so it
# must be real gzip CSV)
import gzip
STATS_BODY = gzip.compress(b"player_id,season,season_type,week,recent_team\n", mtime=0)
SCHED_BODY = ( "game_id,season,game_type,week,gameday,gametime,away_team,home_team\n")


def run_rec(api, sid="S1", t="2026-10-25T16:30:00Z", cap=CAP, ko=KO, rows=None,
            stored=True, shas=(SHA, SSHA)):
    SHA_, SSHA_ = shas
    fp = {}
    for name, s in (("stats", SHA_), ("schedule", SSHA_)):
        c = api.file_commits(BR, pv.fetch_record_path(s))
        fp[name] = {"event": ev_for(api, c[0])} if (stored and c) else {}
        d = api.file_commits(BR, pv.data_record_path(s, pv.DATA_EXT[name]))
        if stored and d:
            fp[name]["data_event"] = ev_for(api, d[0])
    # port (re-audit 353147d5): run records now cite a pricer and a board
    # input record; the fake pricer replays the board's rows
    from fake_github_api import FAKE_PRICER_SHA, publish_board
    bsha = publish_board(api, {"slate_id": sid, "season": 2026, "week": 8,
                               "captured_at": cap, "rows": rows or []}, "2026-10-25T15:10:00Z")
    fzc = api.file_commits(BR, pv.FREEZE_PATH)   # port: store FREEZE event too
    if stored and fzc:
        fp["freeze"] = {"event": ev_for(api, fzc[0])}
    bc = api.file_commits(BR, pv.board_record_path(bsha, 2026, 8))
    if stored and bc:
        fp["board"] = {"event": ev_for(api, bc[0])}
    rec = {"slate_id": sid, "captured_at": cap, "first_kickoff": ko, "season": 2026,
           "week": 8, "pricer_sha256": FAKE_PRICER_SHA,
           "inputs": {"board": bsha, "stats": SHA_, "schedule": SSHA_, "player_data": {}},
           "schedule_kickoffs": {}, "game_teams": {},
           "stats_sha256": SHA_, "schedule_sha256": SSHA_,
           "fetch_provenance": fp, "rows": rows or []}
    return api.commit(BR, {pv.run_record_path(sid): json.dumps(rec)}, t)


class TestConstantsG(unittest.TestCase):
    def test_repo_lowercase(self):
        self.assertEqual(pv.REPO, "sportsedge")
        self.assertEqual(pv.OWNER, "isaacrome21-sys")


class TestRecordProofA(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()
        self.path = pv.fetch_record_path(SHA)

    def code(self, stored=None):
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.prove_record(self.api, self.path, stored_event=stored)
        return cm.exception.code

    def test_single_commit_live_proof(self):
        c = fetch(self.api, SHA)
        p = pv.prove_record(self.api, self.path)
        self.assertEqual(p["commit"], c)
        self.assertEqual(p["pushed_at"], "2026-10-25T15:00:00+00:00")
        self.assertEqual(p["proof_source"], "live_activity")
        self.assertEqual(set(p["event"]), {"id", "before", "after", "timestamp",
                                           "activity_type"})

    def test_edited_record_refused(self):
        fetch(self.api, SHA)
        self.api.commit(BR, {self.path: json.dumps({"sha256": SHA, "x": 1})},
                        "2026-10-25T15:05:00Z")
        self.assertEqual(self.code(), "RECORD_NOT_SINGLE_COMMIT")

    def test_deleted_and_readded_refused(self):
        fetch(self.api, SHA)
        self.api.commit(BR, {self.path: None}, "2026-10-25T15:05:00Z")
        fetch(self.api, SHA, "2026-10-25T15:06:00Z")
        self.assertEqual(self.code(), "RECORD_NOT_SINGLE_COMMIT")

    def test_blob_mismatch_refused(self):
        fetch(self.api, SHA)
        # head blob differs from the proven commit's blob (rewrite)
        orig = self.api.blob_sha
        self.api.blob_sha = lambda ref, path: "f" * 40 if ref == BR else orig(ref, path)
        self.assertEqual(self.code(), "RECORD_BLOB_MISMATCH")

    def test_force_push_refused(self):
        c = fetch(self.api, SHA)
        self.api.push_event(BR, c, c, "2026-10-25T15:10:00Z", kind="force_push")
        self.assertEqual(self.code(), "RECORDS_BRANCH_REWRITTEN")

    def test_branch_deletion_refused(self):
        c = fetch(self.api, SHA)
        self.api.push_event(BR, c, "0" * 40, "2026-10-25T15:10:00Z",
                            kind="branch_deletion")
        self.assertEqual(self.code(), "RECORDS_BRANCH_REWRITTEN")

    def test_multi_commit_push_refused_G(self):
        fetch(self.api, SHA, n_commits=2)
        self.assertEqual(self.code(), "PUSH_NOT_SINGLE_COMMIT")

    def test_not_on_branch(self):
        self.assertEqual(self.code(), "RECORD_NOT_ON_BRANCH")

    def test_stored_event_accepted_when_live_gone_F(self):
        c = fetch(self.api, SHA)
        ev = dict(ev_for(self.api, c))
        self.api.events.clear()                       # aged out (~90 days)
        self.assertEqual(self.code(), "PUSH_UNPROVEN")
        p = pv.prove_record(self.api, self.path, stored_event=ev)
        self.assertEqual(p["proof_source"], "stored_event_commit_checked")
        self.assertEqual(p["pushed_at"], "2026-10-25T15:00:00+00:00")

    def test_stored_event_cross_checked_F(self):
        c = fetch(self.api, SHA)
        ev = dict(ev_for(self.api, c))
        self.api.events.clear()
        self.assertEqual(self.code(dict(ev, after="f" * 40)), "STORED_EVENT_MISMATCH")
        self.assertEqual(self.code(dict(ev, before="f" * 40)), "STORED_EVENT_MISMATCH")
        self.assertEqual(self.code({"after": c}), "API_MALFORMED")

    def test_malformed_api_is_coded_G(self):
        fetch(self.api, SHA)
        for m in ("activities", "file_commits", "get_file"):
            with self.subTest(method=m):
                self.api.malformed = {m}
                self.assertEqual(self.code(), "API_MALFORMED")
        self.api.malformed = set()

    def test_raising_api_is_coded(self):
        class Boom(FakeGitHub):
            def activity_page(self, b, cursor=None):
                raise OSError("network down")
        self.api = Boom()
        fetch(self.api, SHA)
        self.assertEqual(self.code(), "API_UNAVAILABLE")


class TestFetchAndSlateC(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()
        self.st = publish_data(self.api, STATS_BODY, "2026-10-25T15:00:00Z", "stats", "csv.gz")
        self.sc = publish_data(self.api, SCHED_BODY, "2026-10-25T15:01:00Z")
        self.shas = (self.st, self.sc)
        _rr = run_rec
        self.run_rec = lambda api, **kw: _rr(api, shas=self.shas, **kw)

    def test_pricer_gate(self):
        out = pv.require_fetch_provenance(self.api, {"stats": self.st, "schedule": self.sc}, CAP)
        self.assertEqual(out["stats"]["event"]["timestamp"], "2026-10-25T15:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.require_fetch_provenance(self.api, {"stats": "c" * 64}, CAP)
        self.assertEqual(cm.exception.code, "DATA_RECORD_NOT_ON_BRANCH")  # ported: data record first

    def test_fetch_record_hash_mismatch(self):
        self.api.commit(BR, {pv.fetch_record_path("d" * 64): json.dumps({"sha256": SHA})},
                        "2026-10-25T15:02:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.verify_fetch(self.api, "d" * 64, CAP)
        self.assertEqual(cm.exception.code, "FETCH_RECORD_HASH_MISMATCH")

    def test_empty_slate_preserves_provenance_but_cannot_count(self):
        self.run_rec(self.api)
        st = pv.load_slate(self.api, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertEqual(st["reasons"], ["RUN_NO_PRICED_ROWS"])
        for name in ("stats", "schedule"):
            self.assertEqual(st[f"{name}_fetch_proof"]["proof_source"], "live_activity")
        self.assertEqual(st["run_proof"]["pushed_at"], "2026-10-25T16:30:00+00:00")

    def test_run_push_before_capture_is_screen(self):
        self.run_rec(self.api, t="2026-10-25T15:59:00Z")
        st = pv.load_slate(self.api, "S1")
        self.assertIn("RUN_PUSH_BEFORE_CAPTURE", st["reasons"])

    def test_run_push_at_kickoff_is_screen(self):
        self.run_rec(self.api, t=KO)
        self.assertIn("RUN_PUSH_NOT_BEFORE_KICKOFF", pv.load_slate(self.api, "S1")["reasons"])

    def test_fetch_after_capture_screen(self):
        self.run_rec(self.api, cap="2026-10-25T14:00:00Z", t="2026-10-25T16:30:00Z")
        self.assertIn("FETCH_PUSH_NOT_BEFORE_CAPTURE",
                      pv.load_slate(self.api, "S1")["reasons"])

    def test_fetch_push_must_precede_run_push(self):
        # run pushed, THEN a new fetch record for a hash it cites
        self.api2 = FakeGitHub()
        publish_data(self.api2, SCHED_BODY, "2026-10-25T15:01:00Z")
        self.api2.commit(BR, {pv.data_record_path(self.st, "csv.gz"): STATS_BODY},
                         "2026-10-25T15:02:00Z")
        rec = {"slate_id": "S1", "captured_at": "2026-10-25T16:00:00Z", "season": 2026, "week": 8,
               "schedule_kickoffs": {}, "game_teams": {},
               "first_kickoff": "2026-10-25T18:00:00Z", "stats_sha256": self.st,
               "schedule_sha256": self.sc, "fetch_provenance": {}, "rows": []}
        self.api2.commit(BR, {pv.run_record_path("S1"): json.dumps(rec)}, "2026-10-25T16:20:00Z")
        fetch(self.api2, self.st, "2026-10-25T16:40:00Z")
        st = pv.load_slate(self.api2, "S1")
        self.assertEqual(st["status"], "SCREEN")
        # This deliberately minimal record lacks replay inputs; assert the
        # independent fetch chronology check is reached despite that refusal.
        self.assertEqual(st["stats_fetch_proof"]["pushed_at"],
                         "2026-10-25T16:40:00+00:00")
        self.assertIn("FETCH_PUSH_NOT_BEFORE_RUN_PUSH", st["reasons"])

    def test_run_record_edited_screen(self):
        self.run_rec(self.api)
        self.run_rec(self.api, t="2026-10-25T16:40:00Z", rows=[{"edited": 1}])
        self.assertIn("RUN_RECORD_NOT_SINGLE_COMMIT", pv.load_slate(self.api, "S1")["reasons"])

    def test_missing_run_record_screen(self):
        self.assertIn("RUN_RECORD_NOT_ON_BRANCH", pv.load_slate(self.api, "S9")["reasons"])

    def test_malformed_run_record_screen(self):
        self.api.commit(BR, {pv.run_record_path("S1"): "{not json"}, "2026-10-25T16:30:00Z")
        self.assertIn("RUN_RECORD_MALFORMED", pv.load_slate(self.api, "S1")["reasons"])

    def test_stored_fetch_events_used_when_live_gone(self):
        self.run_rec(self.api)
        keep = [e for e in self.api.events
                if e["after"] == self.api.file_commits(BR, pv.run_record_path("S1"))[0]]
        self.api.events[:] = keep                      # fetch events aged out
        st = pv.load_slate(self.api, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertEqual(st["reasons"], ["RUN_NO_PRICED_ROWS"])
        for name in ("stats", "schedule"):
            self.assertEqual(st[f"{name}_fetch_proof"]["proof_source"],
                             "stored_event_commit_checked")


class TestReviewB_DE(unittest.TestCase):
    def tearDown(self):
        sc._utcnow = self._now

    def setUp(self):
        from datetime import datetime, timezone
        self._now = sc._utcnow
        sc._utcnow = lambda: datetime(2026, 11, 30, tzinfo=timezone.utc)
        self.api = FakeGitHub()
        self.wt = records_worktree()

    def publish(self, led):
        return ledger_to_branch(self.api, led), None, None

    def test_rows_and_hashes_come_from_pushed_records(self):
        ids, caps, setl = self.publish(_ledger(5, 14, 3, clv=0.02))
        v = sc.review(ids, records_worktree=self.wt, api=self.api)
        self.assertEqual(v["status"], "REVIEWED")
        self.assertEqual(v["verdict"], "BEATS_MARKET")
        self.assertEqual(v["review_slate"], "2026-W4")
        want = [self.api.get_file(BR, pv.run_record_path(s)) for s in ids[:4]]
        self.assertEqual(v["inputs"]["run_records"], want)
        self.assertEqual(v["inputs_sha256"], sc.inputs_sha256(v["inputs"]))

    def test_caller_cannot_pass_rows(self):
        with self.assertRaises(TypeError):
            sc.review(["S1"], records_worktree=self.wt, api=self.api, rows=[])

    def test_unknown_slate_is_screen(self):
        ids, caps, setl = self.publish(_ledger(4, 14, 3, clv=0.02))
        v = sc.review(["nope"] + ids, records_worktree=self.wt, api=self.api)
        self.assertEqual(v["screen_slates"], ["nope"])

    def test_verdict_existence_via_api(self):
        ids, caps, setl = self.publish(_ledger(5, 14, 3, clv=0.02))
        self.api.commit(BR, {pv.VERDICT_PATH: "{}"}, "2026-11-20T00:00:00Z")
        with self.assertRaises(sc.ReviewAlreadyRecorded):
            sc.review(ids, records_worktree=self.wt, api=self.api)

    def test_verdict_ever_committed_then_deleted_refused(self):
        ids, caps, setl = self.publish(_ledger(5, 14, 3, clv=0.02))
        self.api.commit(BR, {pv.VERDICT_PATH: "{}"}, "2026-11-20T00:00:00Z")
        self.api.commit(BR, {pv.VERDICT_PATH: None}, "2026-11-20T00:01:00Z")
        with self.assertRaises(sc.ReviewAlreadyRecorded):
            sc.review(ids, records_worktree=self.wt, api=self.api)

    def test_origin_url_enforced(self):
        ids, caps, setl = self.publish(_ledger(5, 14, 3, clv=0.02))
        for url in ("https://github.com/someone/sportsedge.git", "/tmp/origin.git"):
            with self.subTest(url=url):
                with self.assertRaises(sc.RecordsLocationRefused):
                    sc.review(ids, records_worktree=records_worktree(url),
                              api=self.api)
        for url in ("git@github.com:isaacrome21-sys/SportsEdge.git",
                    "https://github.com/isaacrome21-sys/sportsedge"):
            with self.subTest(url=url):
                v = sc.review(ids, records_worktree=records_worktree(url),
                              api=self.api)
                self.assertEqual(v["status"], "REVIEWED")

    def test_verdict_counts_only_when_pushed_single_commit(self):
        ids, caps, setl = self.publish(_ledger(5, 14, 3, clv=0.02))
        sc.review(ids, records_worktree=self.wt, api=self.api)
        self.assertTrue((self.wt / pv.VERDICT_PATH).exists())
        self.assertFalse(sc.verdict_counts(self.api))
        self.api.commit(BR, {pv.VERDICT_PATH: (self.wt / pv.VERDICT_PATH).read_text()},
                        "2026-11-20T00:00:00Z")
        self.assertTrue(sc.verdict_counts(self.api))

    def test_close_timestamp_invalid_still_applies(self):
        caps = [{"game_id": "g1", "player_id": "P", "yes_price": 200,
                 "captured_at": "garbage"}]
        self.assertEqual(sc.find_close(caps, "g1", "P", KO), "CLOSE_TIMESTAMP_INVALID")

# port (re-audit 8d86e7a9): the fake pricer is patched in by fixture, never
# registered on import; review tests patch the env guard explicitly.
from fake_github_api import module_fixtures as _mf
setUpModule, tearDownModule = _mf(guard=True)

if __name__ == "__main__":
    unittest.main()

