"""v1.1 re-audit of 87236180: kickoffs recomputed from the schedule data
record on the branch, never from the run record. RED first.
Run: python3 -m unittest test_nfl_atd_v11_branchdata -v
"""
import hashlib
import json
import unittest

import atd_provenance as pv
from fake_github_api import FakeGitHub, ledger_to_records, publish_data, schedule_csv

BR = pv.RECORDS_BRANCH
KO = "2026-10-25T17:00:00Z"
CAP = "2026-10-25T16:00:00Z"


def led():
    return [{"slate_id": "S1", "rows": [
        {"player_id": "a", "selection": "YES", "game_id": "g1", "week": 8,
         "raw_implied": 0.3, "clv": 0.02, "clv_status": "OK",
         "outcome": 1, "outcome_status": "SETTLED"},
        {"player_id": "c", "selection": "YES", "game_id": "g2", "week": 8,
         "raw_implied": 0.3, "clv": 0.02, "clv_status": "OK",
         "outcome": 1, "outcome_status": "SETTLED"}]}]


class TestDataRecords(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(pv.data_record_path("c" * 64), f"nfl_atd_v1_1/data/{'c' * 64}.csv")
        self.assertEqual(pv.data_record_path("c" * 64, "csv.gz"),
                         f"nfl_atd_v1_1/data/{'c' * 64}.csv.gz")

    def test_load_data_record_ok(self):
        api = FakeGitHub()
        sha = publish_data(api, "x,y\n1,2\n", "2026-10-25T15:00:00Z")
        d = pv.load_data_record(api, sha)
        self.assertEqual(d["bytes"], b"x,y\n1,2\n")
        self.assertEqual(d["pushed_at"], "2026-10-25T15:00:00+00:00")

    def test_binary_stats_record(self):
        api = FakeGitHub()
        sha = publish_data(api, b"\x1f\x8b\x00\xffbinary", "2026-10-25T15:00:00Z",
                           name="stats", ext="csv.gz")
        self.assertEqual(pv.load_data_record(api, sha, "csv.gz")["bytes"], b"\x1f\x8b\x00\xffbinary")

    def test_missing_data_record(self):
        api = FakeGitHub()
        api.commit(BR, {pv.fetch_record_path("d" * 64): json.dumps({"sha256": "d" * 64})},
                   "2026-10-25T15:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_data_record(api, "d" * 64)
        self.assertEqual(cm.exception.code, "DATA_RECORD_NOT_ON_BRANCH")

    def test_data_without_fetch_record(self):
        api = FakeGitHub()
        body = "x\n"
        sha = hashlib.sha256(body.encode()).hexdigest()
        api.commit(BR, {pv.data_record_path(sha): body}, "2026-10-25T15:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_data_record(api, sha)
        self.assertEqual(cm.exception.code, "FETCH_RECORD_NOT_ON_BRANCH")

    def test_data_hash_mismatch(self):
        api = FakeGitHub()
        sha = hashlib.sha256(b"real").hexdigest()
        api.commit(BR, {pv.data_record_path(sha): "forged"}, "2026-10-25T15:00:00Z")
        api.commit(BR, {pv.fetch_record_path(sha): json.dumps({"sha256": sha})},
                   "2026-10-25T15:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_data_record(api, sha)
        self.assertEqual(cm.exception.code, "DATA_RECORD_HASH_MISMATCH")

    def test_edited_data_record(self):
        api = FakeGitHub()
        sha = publish_data(api, "x\n", "2026-10-25T15:00:00Z")
        api.commit(BR, {pv.data_record_path(sha): "y\n"}, "2026-10-25T15:05:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_data_record(api, sha)
        self.assertEqual(cm.exception.code, "DATA_RECORD_NOT_SINGLE_COMMIT")

    def test_pricer_gate_requires_data_records(self):
        api = FakeGitHub()
        api.commit(BR, {pv.fetch_record_path("d" * 64): json.dumps({"sha256": "d" * 64})},
                   "2026-10-25T15:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.require_fetch_provenance(api, {"schedule": "d" * 64}, CAP)
        self.assertEqual(cm.exception.code, "DATA_RECORD_NOT_ON_BRANCH")

    def test_pricer_gate_data_pushed_after_capture(self):
        api = FakeGitHub()
        sha = publish_data(api, "x\n", "2026-10-25T16:30:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.require_fetch_provenance(api, {"schedule": sha}, CAP)
        self.assertIn(cm.exception.code, ("FETCH_PUSH_NOT_BEFORE_CAPTURE",
                                          "DATA_PUSH_NOT_BEFORE_CAPTURE"))


class TestRecomputedKickoffs(unittest.TestCase):
    def test_honest_record_counts_with_recomputed_kickoffs(self):
        api = FakeGitHub()
        ledger_to_records(api, led())
        st = pv.load_slate(api, "S1")
        self.assertEqual(st["status"], "COUNTS", st["reasons"])
        self.assertEqual(st["kickoffs"], {"g1": "2026-10-25T17:00:00+00:00",
                                          "g2": "2026-10-25T17:00:00+00:00"})

    def test_forged_later_kickoff_is_screen(self):
        api = FakeGitHub()
        # rows + first_kickoff claim 20:25Z; the pushed schedule says 17:00Z
        ledger_to_records(api, led(), kickoff="2026-10-25T20:25:00Z", schedule_ko=KO)
        st = pv.load_slate(api, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("ROW_KICKOFF_SCHEDULE_MISMATCH", st["reasons"])

    def test_forged_kickoff_days_later_is_screen(self):
        api = FakeGitHub()
        ledger_to_records(api, led(), kickoff="2026-10-28T17:00:00Z", schedule_ko=KO)
        self.assertIn("ROW_KICKOFF_SCHEDULE_MISMATCH", pv.load_slate(api, "S1")["reasons"])

    def test_schedule_kickoffs_field_not_trusted(self):
        api = FakeGitHub()
        ledger_to_records(api, led(), kickoff="2026-10-25T20:25:00Z", schedule_ko=KO)
        rec = json.loads(api.get_file(BR, pv.run_record_path("S1")))
        self.assertEqual(rec["schedule_kickoffs"]["g1"], "2026-10-25T20:25:00Z")  # self-consistent forgery
        self.assertEqual(pv.load_slate(api, "S1")["status"], "SCREEN")

    def test_first_kickoff_must_equal_earliest(self):
        api = FakeGitHub()
        ledger_to_records(api, led(), first_kickoff="2026-10-25T20:00:00Z")
        st = pv.load_slate(api, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("FIRST_KICKOFF_MISMATCH", st["reasons"])

    def test_schedule_data_missing_is_screen(self):
        api = FakeGitHub()
        ledger_to_records(api, led())
        rec = json.loads(api.get_file(BR, pv.run_record_path("S1")))
        api2 = FakeGitHub()
        # same run record, but the schedule data record was never pushed
        for name in ("stats",):
            pass
        api2.commit(BR, {pv.fetch_record_path(rec["schedule_sha256"]):
                         json.dumps({"sha256": rec["schedule_sha256"]})}, "2026-10-25T15:01:00Z")
        api2.commit(BR, {pv.fetch_record_path(rec["stats_sha256"]):
                         json.dumps({"sha256": rec["stats_sha256"]})}, "2026-10-25T15:00:00Z")
        for name in ("stats", "schedule"):
            c = api2.file_commits(BR, pv.fetch_record_path(rec[f"{name}_sha256"]))[0]
            rec["fetch_provenance"][name]["event"] = next(e for e in api2.events if e["after"] == c)
        api2.commit(BR, {pv.run_record_path("S1"): json.dumps(rec)}, "2026-10-25T16:30:00Z")
        st = pv.load_slate(api2, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("DATA_RECORD_NOT_ON_BRANCH", st["reasons"])

    def test_missing_game_teams_malformed(self):
        api = FakeGitHub()
        ledger_to_records(api, led())
        rec = json.loads(api.get_file(BR, pv.run_record_path("S1")))
        del rec["game_teams"]
        api.commit(BR, {pv.run_record_path("S2"): json.dumps(dict(rec, slate_id="S2"))},
                   "2026-10-25T16:31:00Z")
        self.assertIn("RUN_RECORD_MALFORMED", pv.load_slate(api, "S2")["reasons"])

    def test_close_window_uses_recomputed_kickoff(self):
        # games map handed to load_closes comes from the recomputed kickoffs
        import score_nfl_atd_forward as sc
        api = FakeGitHub()
        ledger_to_records(api, led())
        st = pv.load_slate(api, "S1")
        g = sc._games([st])
        self.assertEqual(g["g1"]["kickoff"], "2026-10-25T17:00:00+00:00")

# port (re-audit 8d86e7a9): the fake pricer is patched in by fixture, never
# registered on import.
from fake_github_api import module_fixtures as _mf
setUpModule, tearDownModule = _mf(guard=False)

if __name__ == "__main__":
    unittest.main()
