"""Research-only selected-team spread contract/CLV regression."""
import copy
import json
import unittest
from pathlib import Path
from scripts.grade_cfb_unsupported_spreads import grade
SOURCE=Path(__file__).resolve().parents[1]/"ledger/cfb_unsupported_spreads/2026-10-10-opening.json"

class UnsupportedSpreadGraderTest(unittest.TestCase):
    def setUp(self):
        self.ledger=json.loads(SOURCE.read_text())
        self.first=self.ledger["contracts"][0]
    def close(self,handicap=21,price=-120,observed="2026-10-11T02:15:00Z"):
        return {"id":self.first["id"],"pick_team_canonical":"Hawaii",
          "handicap":handicap,"price_american":price,"book":"DraftKings",
          "observed_at_utc":observed,"source_ref":"fixture://manual-close","verified":False}
    def final(self,away=14,home=33,observed="2026-10-11T05:00:00Z"):
        return {"id":self.first["id"],"away_points":away,"home_points":home,
          "status":"FINAL","observed_at_utc":observed,"source_ref":"fixture://score"}
    def test_initial_eight_pending(self):
        a=grade(self.ledger,[],[])
        self.assertEqual(a["summary"]["tracked"],8)
        self.assertEqual(a["summary"]["pending_results"],8)
        self.assertFalse(a["probation"])
    def test_original_line_settlement_and_moved_line_clv(self):
        a=grade(self.ledger,[self.close(19.5,-115)],[self.final()])
        x=a["rows"][0]
        self.assertEqual(x["result"],"WIN")
        self.assertAlmostEqual(x["paper_pnl_units"],.223214,places=6)
        self.assertEqual(x["line_clv_points"],1.5)
        self.assertIsNone(x["same_line_price_clv_implied_pp"])
    def test_push_original_line(self):
        x=grade(self.ledger,[],[self.final(14,35)])["rows"][0]
        self.assertEqual(x["result"],"PUSH")
        self.assertEqual(x["paper_pnl_units"],0)
    def test_same_line_juice_clv(self):
        x=grade(self.ledger,[self.close()],[])["rows"][0]
        self.assertGreater(x["same_line_price_clv_implied_pp"],0)
    def test_late_close_forbidden(self):
        with self.assertRaisesRegex(ValueError,"CLOSE_NOT_LAST_HOUR_PREGAME"):
            grade(self.ledger,[self.close(observed="2026-10-11T03:15:00Z")],[])
    def test_unsupported_relabel_forbidden(self):
        s=copy.deepcopy(self.ledger)
        s["contracts"][0]["status"]="OFFICIAL"
        with self.assertRaisesRegex(ValueError,"ORIGINAL_CONTRACT_NOT_FROZEN"):
            grade(s,[],[])
    def test_after_kickoff_result_guard(self):
        with self.assertRaisesRegex(ValueError,"RESULT_OBSERVED_BEFORE_KICKOFF"):
            grade(self.ledger,[],[self.final(observed="2026-10-11T02:00:00Z")])
    def test_unknown_close_rejected(self):
        bad=self.close()
        bad["id"]="UNKNOWN"
        with self.assertRaisesRegex(ValueError,"UNKNOWN_OBSERVATION_ID"):
            grade(self.ledger,[bad],[])

if __name__=="__main__": unittest.main()
