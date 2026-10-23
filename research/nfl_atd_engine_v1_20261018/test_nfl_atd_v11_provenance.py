"""v1.1 re-audit (eb9d47aa NOT CLEARED): server-side provenance, fixed
verdict path on a records branch, CLOSE_TIMESTAMP_INVALID. RED first.
Run: python3 -m unittest test_nfl_atd_v11_provenance -v
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import atd_provenance as pv
import score_nfl_atd_forward as sc
from test_nfl_atd_v11_scorer import _ledger

SHA = "a" * 64
SSHA = "b" * 64
CAP = "2026-10-25T11:00:00-05:00"   # 16:00Z
KO = "2026-10-25T12:00:00-05:00"    # 17:00Z


class FakeAPI:
    """Stands in for the GitHub REST API (contents, commits?path=, and the
    repository activity endpoint with server-side push timestamps)."""
    def __init__(self):
        self.files = {}        # (branch, path) -> (content, add_commit)
        self.pushes = []       # {"ref", "after", "timestamp"}

    def put(self, branch, path, content, commit, pushed_at):
        self.files[(branch, path)] = (content, commit)
        if pushed_at is not None:
            self.pushes.append({"ref": f"refs/heads/{branch}",
                                "after": commit, "timestamp": pushed_at,
                                "activity_type": "push"})

    def get_file(self, branch, path):
        f = self.files.get((branch, path))
        return None if f is None else f[0]

    def file_commits(self, branch, path):
        f = self.files.get((branch, path))
        return [] if f is None else [f[1]]

    def push_activities(self, branch):
        return [p for p in self.pushes if p["ref"] == f"refs/heads/{branch}"]


def fetch_rec(sha, name="stats_player_week_2026.csv.gz"):
    return json.dumps({"file": name, "sha256": sha,
                       "fetched_at": "2026-10-25T14:00:00+00:00"})


class TestConstants(unittest.TestCase):
    def test_fixed_names(self):
        self.assertEqual(pv.RECORDS_BRANCH, "records/nfl-atd-v1-1")
        self.assertEqual(pv.VERDICT_PATH, "nfl_atd_v1_1/VERDICT.json")
        self.assertEqual(pv.fetch_record_path(SHA), f"nfl_atd_v1_1/fetch/{SHA}.json")
        self.assertEqual(pv.run_record_path("2026-W8-SUN"),
                         "nfl_atd_v1_1/runs/2026-W8-SUN.json")
        self.assertEqual(pv.SERVER_TIME_SOURCE,
                         "GET /repos/{owner}/{repo}/activity (activity_type=push, timestamp)")


class TestFetchProvenance(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()

    def put_fetch(self, sha=SHA, pushed="2026-10-25T15:00:00Z", rec_sha=None):
        self.api.put(pv.RECORDS_BRANCH, pv.fetch_record_path(sha),
                     fetch_rec(rec_sha or sha), "c" + sha[:7], pushed)

    def code(self, **kw):
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.verify_fetch(self.api, kw.get("sha", SHA), CAP)
        return cm.exception.code

    def test_ok(self):
        self.put_fetch()
        t = pv.verify_fetch(self.api, SHA, CAP)
        self.assertEqual(t["server_pushed_at"], "2026-10-25T15:00:00+00:00")
        self.assertEqual(t["source"], pv.SERVER_TIME_SOURCE)

    def test_not_on_branch(self):
        self.assertEqual(self.code(), "FETCH_RECORD_NOT_ON_BRANCH")

    def test_hash_mismatch(self):
        self.put_fetch(rec_sha="d" * 64)
        self.assertEqual(self.code(), "FETCH_RECORD_HASH_MISMATCH")

    def test_no_server_push_event(self):
        self.put_fetch(pushed=None)
        self.assertEqual(self.code(), "FETCH_PUSH_UNPROVEN")

    def test_pushed_after_capture(self):
        self.put_fetch(pushed="2026-10-25T16:00:00Z")   # == capture
        self.assertEqual(self.code(), "FETCH_PUSH_NOT_BEFORE_CAPTURE")

    def test_committer_date_ignored(self):
        # Only the server activity timestamp is consulted; a record whose
        # content claims an early time but was pushed late fails.
        self.put_fetch(pushed="2026-10-25T18:00:00Z")
        self.assertEqual(self.code(), "FETCH_PUSH_NOT_BEFORE_CAPTURE")


def slate(sid="2026-W8-SUN", cap=CAP, ko=KO):
    return {"slate_id": sid, "captured_at": cap, "first_kickoff": ko,
            "stats_sha256": SHA, "schedule_sha256": SSHA, "rows": []}


class TestSlateStatus(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        for s, t in ((SHA, "2026-10-25T15:00:00Z"), (SSHA, "2026-10-25T15:01:00Z")):
            self.api.put(pv.RECORDS_BRANCH, pv.fetch_record_path(s),
                         fetch_rec(s), "c" + s[:7], t)

    def put_run(self, pushed):
        self.api.put(pv.RECORDS_BRANCH, pv.run_record_path("2026-W8-SUN"),
                     "{}", "run1", pushed)

    def test_counts(self):
        self.put_run("2026-10-25T16:30:00Z")
        st = pv.slate_status(self.api, slate())
        self.assertEqual(st["status"], "COUNTS")
        self.assertEqual(st["run_server_pushed_at"], "2026-10-25T16:30:00+00:00")

    def test_run_pushed_at_kickoff_is_screen(self):
        self.put_run("2026-10-25T17:00:00Z")
        st = pv.slate_status(self.api, slate())
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("RUN_PUSH_NOT_BEFORE_KICKOFF", st["reasons"])

    def test_no_run_record_is_screen(self):
        st = pv.slate_status(self.api, slate())
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("RUN_RECORD_NOT_ON_BRANCH", st["reasons"])

    def test_fetch_after_capture_is_screen(self):
        self.put_run("2026-10-25T16:30:00Z")
        st = pv.slate_status(self.api, slate(cap="2026-10-25T09:00:00-05:00"))
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("FETCH_PUSH_NOT_BEFORE_CAPTURE", st["reasons"])


class TestCloseTimestampInvalid(unittest.TestCase):
    K = "2026-10-25T17:00:00Z"

    def test_unparseable_capture_for_player_not_skipped(self):
        caps = [{"game_id": "g1", "player_id": "P", "yes_price": 200,
                 "captured_at": "2026-10-25T16:30:00Z"},
                {"game_id": "g1", "player_id": "P", "yes_price": 150,
                 "captured_at": "garbage"}]
        self.assertEqual(sc.find_close(caps, "g1", "P", self.K),
                         "CLOSE_TIMESTAMP_INVALID")
        caps[1]["captured_at"] = None
        self.assertEqual(sc.find_close(caps, "g1", "P", self.K),
                         "CLOSE_TIMESTAMP_INVALID")

    def test_other_players_bad_timestamp_irrelevant(self):
        caps = [{"game_id": "g1", "player_id": "P", "yes_price": 200,
                 "captured_at": "2026-10-25T16:30:00Z"},
                {"game_id": "g1", "player_id": "Q", "yes_price": 150,
                 "captured_at": "garbage"}]
        self.assertEqual(sc.find_close(caps, "g1", "P", self.K)["yes_price"], 200)


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


class TestVerdictOnRecordsBranch(unittest.TestCase):
    """Real git: a bare 'origin' and a worktree on the records branch."""
    def setUp(self):
        t = Path(tempfile.mkdtemp())
        self.origin = t / "origin.git"
        git(t, "init", "-q", "--bare", str(self.origin))
        self.wt = t / "wt"
        git(t, "init", "-q", "-b", pv.RECORDS_BRANCH, str(self.wt))
        git(self.wt, "config", "user.email", "t@t"); git(self.wt, "config", "user.name", "t")
        (self.wt / "README").write_text("records\n")
        git(self.wt, "add", "."); git(self.wt, "commit", "-qm", "init")
        git(self.wt, "remote", "add", "origin", str(self.origin))
        git(self.wt, "push", "-q", "origin", pv.RECORDS_BRANCH)
        self.api = FakeAPI()

    def led(self):
        led = _ledger(5, 14, 3, clv=0.02)
        for s in led:
            s.update(captured_at=CAP, first_kickoff=KO,
                     stats_sha256=SHA, schedule_sha256=SSHA)
        return led

    def counts_all(self):
        return lambda api, s: {"status": "COUNTS", "reasons": []}

    def test_verdict_staged_at_fixed_path_not_counted_until_pushed(self):
        v = sc.review(self.led(), records_worktree=self.wt, api=self.api,
                      slate_status=self.counts_all())
        self.assertEqual(v["status"], "REVIEWED")
        self.assertTrue((self.wt / pv.VERDICT_PATH).exists())
        self.assertEqual(v["record_state"], "STAGED_NOT_COUNTED")
        self.assertFalse(sc.verdict_counts(self.wt))
        git(self.wt, "add", "."); git(self.wt, "commit", "-qm", "verdict")
        self.assertFalse(sc.verdict_counts(self.wt))    # committed, not pushed
        git(self.wt, "push", "-q", "origin", pv.RECORDS_BRANCH)
        self.assertTrue(sc.verdict_counts(self.wt))

    def test_refuses_if_verdict_on_origin(self):
        sc.review(self.led(), records_worktree=self.wt, api=self.api,
                  slate_status=self.counts_all())
        git(self.wt, "add", "."); git(self.wt, "commit", "-qm", "v")
        git(self.wt, "push", "-q", "origin", pv.RECORDS_BRANCH)
        # fresh worktree that never saw the file locally
        t2 = Path(tempfile.mkdtemp()) / "wt2"
        git(t2.parent, "clone", "-q", "-b", pv.RECORDS_BRANCH, str(self.origin), str(t2))
        (t2 / pv.VERDICT_PATH).unlink()
        with self.assertRaises(sc.ReviewAlreadyRecorded):
            sc.review(self.led(), records_worktree=t2, api=self.api,
                      slate_status=self.counts_all())

    def test_refuses_wrong_branch_or_non_git_dir(self):
        git(self.wt, "checkout", "-q", "-b", "other")
        with self.assertRaises(sc.RecordsLocationRefused):
            sc.review(self.led(), records_worktree=self.wt, api=self.api,
                      slate_status=self.counts_all())
        with self.assertRaises(sc.RecordsLocationRefused):
            sc.review(self.led(), records_worktree=tempfile.mkdtemp(),
                      api=self.api, slate_status=self.counts_all())

    def test_records_dir_argument_gone(self):
        with self.assertRaises(TypeError):
            sc.review(self.led(), records_dir=tempfile.mkdtemp())

    def test_screen_slates_excluded(self):
        led = self.led()
        def st(api, s):
            return ({"status": "SCREEN", "reasons": ["X"]} if s["slate_id"] == "2026-W1"
                    else {"status": "COUNTS", "reasons": []})
        v = sc.review(led, records_worktree=self.wt, api=self.api, slate_status=st)
        self.assertEqual(v["screen_slates"], ["2026-W1"])
        self.assertEqual(v["review_slate"], "2026-W5")   # W1 not counted

    def test_default_slate_status_is_provenance(self):
        v = sc.review(self.led(), records_worktree=self.wt, api=self.api)
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")  # all SCREEN
        self.assertEqual(len(v["screen_slates"]), 5)


class TestPricerRefusesWithoutProvenance(unittest.TestCase):
    def test_refuses(self):
        api = FakeAPI()
        with self.assertRaises(pv.ProvenanceFailed):
            pv.require_fetch_provenance(api, {"stats": SHA, "schedule": SSHA}, CAP)

    def test_ok(self):
        api = FakeAPI()
        for s in (SHA, SSHA):
            api.put(pv.RECORDS_BRANCH, pv.fetch_record_path(s), fetch_rec(s),
                    "c" + s[:7], "2026-10-25T15:00:00Z")
        out = pv.require_fetch_provenance(api, {"stats": SHA, "schedule": SSHA}, CAP)
        self.assertEqual(set(out), {"stats", "schedule"})


if __name__ == "__main__":
    unittest.main()
