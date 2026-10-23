"""v1.1 re-audit of 4ece6f6a (rulings 1-5). RED first; asserts behaviour.
Run: python3 -m unittest test_nfl_atd_v11_reaudit3 -v
"""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import (FakeGitHub, ledger_to_branch, ledger_to_records,
                             publish_close, publish_settlements, records_worktree)
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
KO = "2026-10-25T17:00:00Z"
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)
CAPS = [{"player_id": "a", "yes_price": 200, "captured_at": "2026-10-25T16:30:00Z"},
        {"player_id": "b", "yes_price": 300, "captured_at": "2026-10-25T16:30:00Z"}]
GAMES = {"g1": {"kickoff": KO, "season": 2026, "week": 8}}


def one_slate(api, ko=KO, sched_ko=None):
    led = [{"slate_id": "S1", "rows": [
        {"player_id": "a", "selection": "YES", "game_id": "g1", "week": 8,
         "raw_implied": 0.3, "clv": 0.02, "clv_status": "OK",
         "outcome": 1, "outcome_status": "SETTLED"},
        {"player_id": "b", "selection": "PASS", "game_id": "g1", "week": 8,
         "raw_implied": 0.3, "clv": -0.01, "clv_status": "OK",
         "outcome": 0, "outcome_status": "SETTLED"}]}]
    ledger_to_records(api, led, kickoff=ko)
    if sched_ko is not None:   # republish is an edit; build a fresh record instead
        raise AssertionError("use run_with_schedule")
    return "S1"


class Clock(unittest.TestCase):
    def setUp(self):
        self._now = sc._utcnow
        sc._utcnow = lambda: NOW

    def tearDown(self):
        sc._utcnow = self._now


# ---- 1. close window from the run-record row kickoff + schedule cross-check
class TestCloseKickoff(Clock):
    def test_paths_have_season_week(self):
        self.assertEqual(pv.close_record_path("c" * 64, 2026, 8),
                         f"nfl_atd_v1_1/closes/2026-W8/{'c' * 64}.json")
        self.assertEqual(pv.settlement_data_path("c" * 64, 2026, 8),
                         f"nfl_atd_v1_1/settlements/2026-W8/{'c' * 64}.json")

    def test_close_kickoff_differs_from_row_refuses(self):
        api = FakeGitHub()
        publish_close(api, "g1", "2026-10-25T20:25:00Z", "2026-10-25T16:30:00Z", CAPS,
                      "2026-10-25T16:40:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "CLOSE_KICKOFF_CONFLICT")

    def test_window_uses_row_kickoff_not_close_claim(self):
        # Same instant written in another offset is NOT a conflict.
        api = FakeGitHub()
        publish_close(api, "g1", "2026-10-25T12:00:00-05:00", "2026-10-25T16:30:00Z",
                      CAPS, "2026-10-25T17:15:00Z")
        out = pv.load_closes(api, GAMES)
        self.assertEqual(out["unproven_games"], [])
        api2 = FakeGitHub()
        publish_close(api2, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T17:15:01Z")
        self.assertEqual(pv.load_closes(api2, GAMES)["unproven_games"], ["g1"])

    def test_entry_at_or_after_kickoff_unproven(self):
        api = FakeGitHub()
        caps = [dict(CAPS[0], captured_at=KO)]
        publish_close(api, "g1", KO, "2026-10-25T16:30:00Z", caps, "2026-10-25T17:05:00Z")
        self.assertEqual(pv.load_closes(api, GAMES)["unproven_games"], ["g1"])

    def test_entry_after_push_unproven(self):
        api = FakeGitHub()
        caps = [dict(CAPS[0], captured_at="2026-10-25T16:50:00Z")]
        publish_close(api, "g1", KO, "2026-10-25T16:30:00Z", caps, "2026-10-25T16:45:00Z")
        self.assertEqual(pv.load_closes(api, GAMES)["unproven_games"], ["g1"])

    def test_row_kickoff_must_match_pinned_schedule(self):
        api = FakeGitHub()
        one_slate(api)
        p = pv.run_record_path("S1")
        rec = json.loads(api.get_file(BR, p))
        # Ported (re-audit of 87236180): schedule_kickoffs is no longer
        # trusted; forge the row kickoff (and first_kickoff) instead, and copy
        # the data records the slate now needs.
        for r in rec["rows"]:
            if r["game_id"] == "g1":
                r["kickoff"] = "2026-10-25T18:00:00Z"
        api2 = FakeGitHub()
        for path in api.trees[api.heads[BR]]:
            if path.startswith(("nfl_atd_v1_1/data/", "nfl_atd_v1_1/fetch/")):
                api2.commit(BR, {path: api.trees[api.heads[BR]][path]}, "2026-10-25T15:00:00Z")
        for name in ("stats", "schedule"):
            sha = rec[f"{name}_sha256"]
            c = api2.file_commits(BR, pv.fetch_record_path(sha))[0]
            rec["fetch_provenance"][name]["event"] = next(e for e in api2.events if e["after"] == c)
        api2.commit(BR, {p: json.dumps(rec)}, "2026-10-25T16:30:00Z")
        st = pv.load_slate(api2, "S1")
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("ROW_KICKOFF_SCHEDULE_MISMATCH", st["reasons"])

    def test_schedule_kickoff_lookup_for_pricer(self):
        import tempfile, csv
        from pathlib import Path
        d = Path(tempfile.mkdtemp()) / "games.csv"
        with open(d, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["game_id", "season", "game_type", "week", "gameday", "gametime",
                        "away_team", "home_team", "result"])
            w.writerow(["2026_08_DAL_GB", 2026, "REG", 8, "2026-10-25", "13:00", "DAL", "GB", ""])
        import atd_refresh as rf
        ko = rf.schedule_kickoff(d, 2026, ["DAL", "GB"], "2026-10-25T12:00:00-05:00")
        self.assertEqual(ko["game_id"], "2026_08_DAL_GB")
        self.assertEqual(ko["kickoff"], "2026-10-25T17:00:00+00:00")
        self.assertEqual(ko["week"], 8)
        with self.assertRaises(rf.RefreshFailed) as cm:
            rf.schedule_kickoff(d, 2026, ["DAL", "GB"], "2026-10-25T15:25:00-05:00")
        self.assertEqual(cm.exception.code, "KICKOFF_SCHEDULE_MISMATCH")
        with self.assertRaises(rf.RefreshFailed) as cm:
            rf.schedule_kickoff(d, 2026, ["NYJ", "GB"], "2026-10-25T12:00:00-05:00")
        self.assertEqual(cm.exception.code, "KICKOFF_SCHEDULE_MISMATCH")


# ---- 2. unattributable / unparseable close refuses the review
class TestUnattributable(Clock):
    def test_unparseable_close_refuses(self):
        api = FakeGitHub()
        publish_close(api, None, None, None, None, "2026-10-25T16:40:00Z", raw="{not json")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "CLOSE_RECORD_UNPROVEN")

    def test_close_without_game_refuses(self):
        api = FakeGitHub()
        publish_close(api, None, KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:40:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "CLOSE_RECORD_UNPROVEN")

    def test_close_in_wrong_week_dir_refuses(self):
        api = FakeGitHub()
        publish_close(api, "g1", KO, "2026-10-25T16:30:00Z", CAPS, "2026-10-25T16:40:00Z",
                      week=7)
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "CLOSE_RECORD_UNPROVEN")

    def test_review_refuses(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(5, 14, 3, clv=0.02))
        publish_close(api, None, None, None, None, "2026-10-25T16:59:00Z", raw="garbage")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            sc.review(ids, records_worktree=records_worktree(), api=api)
        self.assertEqual(cm.exception.code, "CLOSE_RECORD_UNPROVEN")


# ---- 3. settlements
class TestSettlements3(Clock):
    def test_duplicate_key_in_one_record_conflict(self):
        api = FakeGitHub()
        publish_settlements(api, {}, "2026-10-26T12:00:00Z", rows=[
            {"game_id": "g1", "player_id": "a", "td": 1},
            {"game_id": "g1", "player_id": "a", "td": 1}])
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_settlements(api, GAMES, NOW)
        self.assertEqual(cm.exception.code, "SETTLEMENT_CONFLICT")

    def test_data_record_push_must_be_after_final(self):
        api = FakeGitHub()
        publish_settlements(api, {("g1", "a"): 1}, "2026-10-26T12:00:00Z",
                            data_pushed_at="2026-10-25T20:00:00Z")   # before 21:00Z final
        out = pv.load_settlements(api, GAMES, NOW)
        self.assertEqual(out["settlements"], {})
        self.assertEqual(out["refused"][0]["code"], "SETTLEMENT_DATA_PUSH_BEFORE_FINAL")

    def test_settlement_wrong_week_dir_refused(self):
        api = FakeGitHub()
        publish_settlements(api, {("g1", "a"): 1}, "2026-10-26T12:00:00Z", week=9)
        out = pv.load_settlements(api, GAMES, NOW)
        self.assertEqual(out["settlements"], {})
        self.assertEqual(out["refused"][0]["code"], "SETTLEMENT_MISFILED")

    def test_unsettled_count_in_verdict(self):
        api = FakeGitHub()
        led = _ledger(5, 14, 3, clv=0.02)
        led[0]["rows"][0]["outcome_status"] = "UNSETTLED"
        ids = ledger_to_branch(api, led)
        v = sc.review(ids, records_worktree=records_worktree(), api=api)
        self.assertEqual(v["n_unsettled"], 1)


# ---- 4. tree listing, branch_creation, pagination
class TestTreeAndEvents(Clock):
    def test_truncated_tree_refuses(self):
        api = FakeGitHub()
        api.truncated = True
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "API_TREE_TRUNCATED")

    def test_tree_malformed_coded(self):
        api = FakeGitHub()
        api.malformed = {"git_tree"}
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_closes(api, GAMES)
        self.assertEqual(cm.exception.code, "API_MALFORMED")

    def test_list_dir_not_used(self):
        api = FakeGitHub()
        api.list_dir = None          # must not be called
        pv.load_closes(api, GAMES)
        pv.load_settlements(api, GAMES, NOW)

    def test_record_in_branch_creation_push_unproven(self):
        api = FakeGitHub(init_records=False)
        api.commit(BR, {pv.fetch_record_path("a" * 64): json.dumps({"sha256": "a" * 64})},
                   "2026-10-25T15:00:00Z")
        self.assertEqual(api.events[-1]["activity_type"], "branch_creation")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.prove_record(api, pv.fetch_record_path("a" * 64))
        self.assertEqual(cm.exception.code, "RECORD_IN_BRANCH_CREATION")

    def test_stored_branch_creation_event_rejected(self):
        api = FakeGitHub(init_records=False)
        c = api.commit(BR, {pv.fetch_record_path("a" * 64): json.dumps({"sha256": "a" * 64})},
                       "2026-10-25T15:00:00Z")
        ev = dict(api.events[-1])
        api.events.clear()
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.prove_record(api, pv.fetch_record_path("a" * 64), stored_event=ev)
        self.assertEqual(cm.exception.code, "RECORD_IN_BRANCH_CREATION")

    def test_pagination_followed(self):
        api = FakeGitHub(page_size=1)
        target = api.commit(BR, {pv.fetch_record_path("a" * 64): json.dumps({"sha256": "a" * 64})},
                            "2026-10-25T15:00:00Z")
        for i in range(5):
            api.commit(BR, {f"x{i}": str(i)}, f"2026-10-25T15:0{i + 1}:00Z")
        p = pv.prove_record(api, pv.fetch_record_path("a" * 64))
        self.assertEqual(p["commit"], target)
        self.assertEqual(p["proof_source"], "live_activity")

    def test_force_push_on_later_page_found(self):
        api = FakeGitHub(page_size=1)
        c = api.commit(BR, {pv.fetch_record_path("a" * 64): json.dumps({"sha256": "a" * 64})},
                       "2026-10-25T15:00:00Z")
        api.push_event(BR, c, c, "2026-10-25T15:00:30Z", kind="force_push")
        for i in range(4):
            api.commit(BR, {f"x{i}": str(i)}, f"2026-10-25T15:0{i + 1}:00Z")
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.prove_record(api, pv.fetch_record_path("a" * 64))
        self.assertEqual(cm.exception.code, "RECORDS_BRANCH_REWRITTEN")


# ---- 5. token required, never printed
class TestToken(Clock):
    def test_real_client_requires_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(pv.ProvenanceFailed) as cm:
                pv.GitHubAPI()
            self.assertEqual(cm.exception.code, "GITHUB_TOKEN_MISSING")

    def test_token_never_in_repr_or_errors(self):
        secret = "ghp_SECRETSECRET123"
        api = pv.GitHubAPI(token=secret)
        self.assertNotIn(secret, repr(api))
        self.assertNotIn(secret, str(vars(api).get("base", "")))

    def test_review_refuses_unauthenticated_api(self):
        api = FakeGitHub(authenticated=False)
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            sc.review([], records_worktree=records_worktree(), api=api)
        self.assertEqual(cm.exception.code, "GITHUB_TOKEN_MISSING")

    def test_pricer_gate_refuses_unauthenticated_api(self):
        api = FakeGitHub(authenticated=False)
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.require_fetch_provenance(api, {"stats": "a" * 64}, "2026-10-25T16:00:00Z")
        self.assertEqual(cm.exception.code, "GITHUB_TOKEN_MISSING")


if __name__ == "__main__":
    unittest.main()
