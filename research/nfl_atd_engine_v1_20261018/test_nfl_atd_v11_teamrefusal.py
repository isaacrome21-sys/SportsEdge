"""v1.1 ruling (Oct 22): PLAYER_TEAM_UNRESOLVED is refused by the pricer
from the pinned stats before pricing; refusal counts reported per slate.
RED first.  Run: python3 -m pytest test_nfl_atd_v11_teamrefusal.py
"""
import gzip
import inspect
import json
import unittest

import atd_provenance as pv
import price_nfl_atd_board_v11 as pr
from fake_github_api import FakeGitHub, ledger_to_records
from test_nfl_atd_v11_branchdata import led

BR = pv.RECORDS_BRANCH


def priced(pid, gid="g1"):
    return {"status": "PRICED", "player_id": pid, "game_id": gid, "player_name": pid,
            "selection": "YES", "raw_implied": 0.3, "p_model": 0.35, "yes_price": 200,
            "kickoff": "2026-10-25T17:00:00Z", "captured_at": "2026-10-25T16:00:00Z"}


class TestPricerRefusal(unittest.TestCase):
    TEAMS = {"a": "KC", "b": "LV", "t": "DEN"}

    def test_found_on_either_team_stays_priced(self):
        rows = [priced("a"), priced("b")]
        self.assertEqual(pr.player_team_refusal(rows, self.TEAMS, ["KC", "LV"]), 0)
        self.assertTrue(all(r["status"] == "PRICED" for r in rows))

    def test_not_found_refused_unpriced(self):
        rows = [priced("rookie")]
        self.assertEqual(pr.player_team_refusal(rows, self.TEAMS, ["KC", "LV"]), 1)
        r = rows[0]
        self.assertEqual((r["status"], r["reason"]), ("UNPRICED", "PLAYER_TEAM_UNRESOLVED"))
        for k in ("raw_implied", "p_model", "selection"):
            self.assertNotIn(k, r)

    def test_stale_trade_refused(self):
        rows = [priced("t")]
        self.assertEqual(pr.player_team_refusal(rows, self.TEAMS, ["KC", "LV"]), 1)
        self.assertEqual(rows[0]["reason"], "PLAYER_TEAM_UNRESOLVED")

    def test_already_unpriced_untouched(self):
        rows = [{"status": "UNPRICED", "reason": "UNPRICED_INVALID_PRICE", "player_id": "zz"}]
        self.assertEqual(pr.player_team_refusal(rows, self.TEAMS, ["KC", "LV"]), 0)
        self.assertEqual(rows[0]["reason"], "UNPRICED_INVALID_PRICE")

    def test_pricer_main_applies_check_and_records_count(self):
        src = inspect.getsource(pr.main)
        self.assertIn("player_team_refusal(", src)
        self.assertIn("pv.stats_teams(", src)
        self.assertIn('"PLAYER_TEAM_UNRESOLVED"', src)


class TestReviewSide(unittest.TestCase):
    def test_refused_row_not_counted_slate_counts(self):
        api = FakeGitHub()
        ledger = led()
        ledger_to_records(api, ledger, player_team={"a": None})
        rec = json.loads(api.get_file(BR, pv.run_record_path("S1")))
        for r in rec["rows"]:
            if r["player_id"] == "a":
                for k in ("raw_implied", "selection", "kickoff", "week"):
                    r.pop(k, None)
                r.update(status="UNPRICED", reason="PLAYER_TEAM_UNRESOLVED")
        api.commit(BR, {pv.run_record_path("S2"): json.dumps(dict(rec, slate_id="S2"))},
                   "2026-10-25T16:45:00Z")
        st = pv.load_slate(api, "S2")
        self.assertEqual(st["status"], "COUNTS", st["reasons"])
        self.assertEqual(st["refusals"], {"PLAYER_TEAM_UNRESOLVED": 1})

    def test_priced_row_failing_check_still_screen(self):
        api = FakeGitHub()
        ledger_to_records(api, led(), player_team={"a": None})
        self.assertIn("ROW_PLAYER_TEAM_MISMATCH", pv.load_slate(api, "S1")["reasons"])

    def test_review_reports_refusals_by_slate(self):
        import score_nfl_atd_forward as sc
        src = inspect.getsource(sc.review)
        self.assertIn("refusals_by_slate", src)


if __name__ == "__main__":
    unittest.main()
