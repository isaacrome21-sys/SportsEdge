"""v1.1: close captures and settlements only from branch records. RED first.
Run: python3 -m unittest test_nfl_atd_v11_closes -v
"""
import hashlib
import json
import unittest
from datetime import datetime, timezone

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import (FakeGitHub, ledger_to_branch, ledger_to_records,
                             publish_close, publish_settlements, records_worktree)
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
KO = "2026-10-25T17:00:00Z"
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)
GAMES = {"g1": {"kickoff": KO, "season": 2026, "week": 8}}


def one_slate(api):
    """One pushed slate: g1 with picks a (YES) and b (PASS)."""
    led = [{"slate_id": "S1", "rows": [
        {"player_id": "a", "selection": "YES", "game_id": "g1", "week": 8,
         "raw_implied": 0.3, "clv": 0.02, "clv_status": "OK",
         "outcome": 1, "outcome_status": "SETTLED"},
        {"player_id": "b", "selection": "PASS", "game_id": "g1", "week": 8,
         "raw_implied": 0.3, "clv": -0.01, "clv_status": "OK",
         "outcome": 0, "outcome_status": "SETTLED"}]}]
    ledger_to_records(api, led)
    return "S1"


CAPS = [{"player_id": "a", "yes_price": 200, "captured_at": "2026-10-25T16:30:00Z"},
        {"player_id": "b", "yes_price": 300, "captured_at": "2026-10-25T16:30:00Z"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()
        self.sid = one_slate(self.api)
        self._now = sc._utcnow
        sc._utcnow = lambda: NOW

    def tearDown(self):
        sc._utcnow = self._now


class TestClosePaths(Base):
    def test_paths(self):
        self.assertEqual(pv.close_record_path("c" * 64, 2026, 8),
                         f"nfl_atd_v1_1/closes/2026-W8/{'c' * 64}.json")
        self.assertEqual(pv.settlement_data_path("c" * 64, 2026, 8),
                         f"nfl_atd_v1_1/settlements/2026-W8/{'c' * 64}.json")

    def test_proven_close_used(self):
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:40:00Z")
        closes = pv.load_closes(self.api, GAMES)
        self.assertEqual(closes["unproven_games"], [])
        self.assertEqual(len(closes["captures"]), 2)
        self.assertEqual(closes["captures"][0]["game_id"], "g1")

    def test_pushed_before_captured_at_unproven(self):
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:29:00Z")
        self.assertEqual(pv.load_closes(self.api, GAMES)["unproven_games"], ["g1"])

    def test_capture_entry_later_than_push_unproven(self):
        caps = [dict(CAPS[0], captured_at="2026-10-25T16:50:00Z")]
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", caps, "2026-10-25T16:40:00Z")
        self.assertEqual(pv.load_closes(self.api, GAMES)["unproven_games"], ["g1"])

    def test_push_window_kickoff_plus_15(self):
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T17:15:00Z")
        self.assertEqual(pv.load_closes(self.api, GAMES)["unproven_games"], [])
        api2 = FakeGitHub()
        publish_close(api2, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T17:15:01Z")
        self.assertEqual(pv.load_closes(api2, GAMES)["unproven_games"], ["g1"])

    def test_filename_must_be_content_sha(self):
        body = json.dumps({"game_id": "g1", "kickoff": KO,
                           "captured_at": "2026-10-25T16:30:00Z", "captures": CAPS})
        self.api.commit(BR, {pv.close_record_path("d" * 64, 2026, 8): body}, "2026-10-25T16:40:00Z")
        self.assertEqual(pv.load_closes(self.api, GAMES)["unproven_games"], ["g1"])

    def test_edited_close_unproven(self):
        sha = publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS,
                            "2026-10-25T16:40:00Z")
        self.api.commit(BR, {pv.close_record_path(sha, 2026, 8): "{}"}, "2026-10-25T16:45:00Z")
        # Ruling 2 (re-audit of 4ece6f6a): an edited record that can no
        # longer be attributed to a game now refuses the whole review.
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(self.api, GAMES)
        self.assertEqual(cm.exception.code, "CLOSE_RECORD_UNPROVEN")

    def test_unproven_close_makes_every_game_row_missing(self):
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:40:00Z")
        publish_close(self.api, "g1", KO, "2026-10-25T16:35:00Z", CAPS, "2026-10-25T18:00:00Z")
        rows = sc.score_slate_rows(self.api, self.sid)
        self.assertEqual({r["clv_reason"] for r in rows}, {"CLOSE_RECORD_UNPROVEN"})
        self.assertTrue(all(r["clv_status"] == "CLV_MISSING" for r in rows))


class TestSettlements(Base):
    def setUp(self):
        super().setUp()
        publish_close(self.api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:40:00Z")

    def test_proven_settlement_grades_rows(self):
        publish_settlements(self.api, {("g1", "a"): 1, ("g1", "b"): 0}, "2026-10-26T12:00:00Z")
        rows = {r["player_id"]: r for r in sc.score_slate_rows(self.api, self.sid)}
        self.assertEqual(rows["a"]["outcome"], 1)
        self.assertEqual(rows["b"]["outcome_status"], "SETTLED")

    def test_settlement_pushed_before_final_not_used(self):
        # final = kickoff + 4h = 21:00Z
        publish_settlements(self.api, {("g1", "a"): 1}, "2026-10-25T20:59:00Z")
        rows = sc.score_slate_rows(self.api, self.sid)
        self.assertTrue(all(r["outcome_status"] == "UNSETTLED" for r in rows))

    def test_settlement_pushed_after_review_not_used(self):
        publish_settlements(self.api, {("g1", "a"): 1}, "2026-12-01T00:00:00Z")
        rows = sc.score_slate_rows(self.api, self.sid)
        self.assertTrue(all(r["outcome_status"] == "UNSETTLED" for r in rows))

    def test_settlement_hash_mismatch_not_used(self):
        body = json.dumps({"settlements": [{"game_id": "g1", "player_id": "a", "td": 1}]})
        sha = hashlib.sha256(body.encode()).hexdigest()
        self.api.commit(BR, {pv.settlement_data_path(sha, 2026, 8): body + " "}, "2026-10-26T12:00:00Z")
        self.api.commit(BR, {pv.fetch_record_path(sha): json.dumps({"sha256": sha})},
                        "2026-10-26T12:00:00Z")
        st = pv.load_settlements(self.api, GAMES, NOW)
        self.assertEqual(st["settlements"], {})
        self.assertEqual(st["refused"][0]["code"], "SETTLEMENT_HASH_MISMATCH")

    def test_settlement_without_fetch_record_not_used(self):
        body = json.dumps({"settlements": [{"game_id": "g1", "player_id": "a", "td": 1}]})
        sha = hashlib.sha256(body.encode()).hexdigest()
        self.api.commit(BR, {pv.settlement_data_path(sha, 2026, 8): body}, "2026-10-26T12:00:00Z")
        st = pv.load_settlements(self.api, GAMES, NOW)
        self.assertEqual(st["settlements"], {})
        self.assertEqual(st["refused"][0]["code"], "FETCH_RECORD_NOT_ON_BRANCH")

    def test_conflicting_settlements_refuse_review(self):
        publish_settlements(self.api, {("g1", "a"): 1}, "2026-10-26T12:00:00Z")
        publish_settlements(self.api, {("g1", "a"): 0}, "2026-10-26T13:00:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_settlements(self.api, GAMES, NOW)
        self.assertEqual(cm.exception.code, "SETTLEMENT_CONFLICT")


class TestReviewReadsOnlyBranch(unittest.TestCase):
    def setUp(self):
        self._now = sc._utcnow
        sc._utcnow = lambda: NOW

    def tearDown(self):
        sc._utcnow = self._now

    def test_captures_settlements_args_rejected(self):
        api = FakeGitHub()
        with self.assertRaises(TypeError):
            sc.review([], records_worktree=records_worktree(), api=api,
                      captures=[], settlements={})

    def test_review_from_branch_only(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(5, 14, 3, clv=0.02))
        v = sc.review(ids, records_worktree=records_worktree(), api=api)
        self.assertEqual(v["status"], "REVIEWED")
        self.assertEqual(v["verdict"], "BEATS_MARKET")
        self.assertEqual(v["review_slate"], "2026-W4")
        self.assertIn("closes", v["inputs"])
        self.assertIn("settlements", v["inputs"])

    def test_late_closes_make_insufficient_close_data(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(5, 14, 3, clv=0.02),
                               close_pushed="2026-10-25T17:20:00Z")
        v = sc.review(ids, records_worktree=records_worktree(), api=api)
        self.assertEqual(v["verdict"], "INSUFFICIENT_CLOSE_DATA")


if __name__ == "__main__":
    unittest.main()
