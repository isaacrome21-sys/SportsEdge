import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.mlb_postseason_k_outs_forward_shadow import MARKET_LINES,_sha
from sportsedge.mlb_postseason_k_outs_forward_readout import (
    ShadowReadoutError,readout,MIN_COMPLETE_STARTS,MIN_INDEPENDENT_GAMES,
)


def create_fixture(root:Path,n_games=30,starters=2):
    pred=root/"predictions";sett=root/"settlements"
    pred.mkdir(parents=True);sett.mkdir(parents=True)
    for i in range(n_games):
        for j in range(starters):
            game=100000+i;pid=500+j
            for market,lines in MARKET_LINES.items():
                for line in lines:
                    name=f"{game}_{pid}_{market}_{str(line).replace('.','p')}.json"
                    p=.61
                    q=.52
                    pre={
                        "schema":"mlb_postseason_k_outs_2026_pit_shadow_v1",
                        "status":"PREGAME_CAPTURED","game_pk":game,"pitcher_id":pid,
                        "market":market,"line":line,
                        "captured_at_utc":"2026-10-09T23:00:00+00:00",
                        "scheduled_first_pitch_utc":"2026-10-10T00:00:00+00:00",
                        "baseline_opponent_adjusted_p_over":p,
                        "postseason_shadow_research_p_over":q,
                        "shadow_transfer_validated":False,
                        "live_market_price_bound":False,"allow_betting_card":False,
                    }
                    pre["receipt_sha256"]=_sha(pre)
                    (pred/name).write_text(json.dumps(pre))
                    actual=3 if market=="PITCHER_K" else 15
                    y=int(actual>line)
                    post={
                        "schema":"mlb_postseason_k_outs_2026_shadow_settlement_v1",
                        "status":"GRADED","game_pk":game,"pitcher_id":pid,
                        "market":market,"line":line,
                        "prediction_receipt_sha256":pre["receipt_sha256"],
                        "settled_at_utc":"2026-10-10T05:00:00+00:00",
                        "actual_count":actual,"actual_over":bool(y),
                        "baseline_brier":(p-y)**2,"shadow_brier":(q-y)**2,
                        "allow_betting_card":False,
                    }
                    post["receipt_sha256"]=_sha(post)
                    (sett/name).write_text(json.dumps(post))


class MLBProspectiveReadoutTests(unittest.TestCase):
    def test_not_due_without_genuine_forward_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            result=readout(Path(td)/"predictions",Path(td)/"settlements")
            self.assertEqual(result["status"],"NOT_DUE_INSUFFICIENT_FORWARD_EVIDENCE")
            self.assertFalse(result["betting_card_eligible"])

    def test_must_have_independent_games_and_complete_start_grid(self):
        self.assertGreater(MIN_COMPLETE_STARTS,25)
        self.assertGreater(MIN_INDEPENDENT_GAMES,20)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);create_fixture(root)
            result=readout(root/"predictions",root/"settlements")
            self.assertEqual(result["status"],"RESEARCH_READOUT_AVAILABLE")
            self.assertEqual(result["complete_pitcher_games"],60)
            self.assertEqual(result["independent_games"],30)
            self.assertEqual(result["combined"]["scored_thresholds_correlated"],300)
            self.assertFalse(result["model_deployment_allowed"])
            self.assertEqual(len(result["game_cluster_descriptive_bootstrap_95_brier_delta"]),2)

    def test_incomplete_starter_unit_is_not_scored(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);create_fixture(root)
            file=next((root/"settlements").glob("100000_500_PITCHER_K_*.json"))
            file.unlink()
            result=readout(root/"predictions",root/"settlements")
            self.assertEqual(result["complete_pitcher_games"],59)
            self.assertEqual(result["incomplete_pitcher_game_groups"],1)

    def test_tampered_prediction_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);create_fixture(root,1,1)
            file=next((root/"predictions").glob("*.json"))
            p=json.loads(file.read_text());p["baseline_opponent_adjusted_p_over"]=.99
            file.write_text(json.dumps(p))
            with self.assertRaises(ShadowReadoutError):
                readout(root/"predictions",root/"settlements")

    def test_settlement_without_pregame_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);create_fixture(root,1,1)
            file=next((root/"predictions").glob("*.json"))
            file.unlink()
            with self.assertRaises(ShadowReadoutError):
                readout(root/"predictions",root/"settlements")

    def test_late_pregame_capture_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);create_fixture(root,1,1)
            file=next((root/"predictions").glob("*.json"))
            p=json.loads(file.read_text())
            p["captured_at_utc"]="2026-10-10T00:00:01+00:00"
            p["receipt_sha256"]=_sha({k:v for k,v in p.items() if k!="receipt_sha256"})
            file.write_text(json.dumps(p))
            with self.assertRaises(ShadowReadoutError):
                readout(root/"predictions",root/"settlements")


if __name__=="__main__":
    unittest.main()
