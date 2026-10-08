import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.mlb_postseason_k_outs_forward_shadow import MARKET_LINES,_sha
from sportsedge.mlb_postseason_k_outs_forward_readout import (
    ShadowReadoutError,readout,game_cluster_bootstrap,MIN_COMPLETE_STARTS,MIN_INDEPENDENT_GAMES,
)
from random import Random


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



    def _rewrite(self, path, **changes):
        row=json.loads(path.read_text())
        row.update(changes)
        row["receipt_sha256"]=_sha({k:v for k,v in row.items() if k!="receipt_sha256"})
        path.write_text(json.dumps(row))

    def test_bootstrap_matches_threshold_weighted_brier_not_game_means(self):
        rows=[]
        for game, deltas in ((1, [0.0]), (2, [1.0, 1.0, 1.0])):
            for delta in deltas:
                rows.append({"game_pk":game,"shadow_brier":delta,"baseline_brier":0.0})
        # Pad to the independent-game floor with equal one-row clusters so the
        # unequal pair still moves the threshold-weighted mean away from the
        # mean of game means.
        for game in range(3, 26):
            rows.append({"game_pk":game,"shadow_brier":0.0,"baseline_brier":0.0})
        reported=sum(r["shadow_brier"]-r["baseline_brier"] for r in rows)/len(rows)
        clusters={}
        for r in rows:
            clusters.setdefault(r["game_pk"], []).append(r["shadow_brier"]-r["baseline_brier"])
        game_mean=sum(sum(v)/len(v) for v in clusters.values())/len(clusters)
        self.assertNotEqual(reported, game_mean)
        rng=Random(2026)
        keys=sorted(clusters)
        sums=[(sum(clusters[k]), len(clusters[k])) for k in keys]
        n=len(sums)
        expected=[]
        for _ in range(2000):
            total=count=0
            for _pick in range(n):
                s,c=sums[rng.randrange(n)]
                total+=s; count+=c
            expected.append(total/count)
        expected.sort()
        self.assertEqual(
            game_cluster_bootstrap(rows, seed=2026),
            [expected[int(.025*len(expected))], expected[int(.975*len(expected))]],
        )

    def test_contradictory_settlement_counts_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_fixture(root,1,1)
            files=sorted((root/"settlements").glob("*_PITCHER_K_*.json"))
            self._rewrite(files[1], actual_count=9, actual_over=True)
            with self.assertRaises(ShadowReadoutError) as caught:
                readout(root/"predictions", root/"settlements")
            self.assertIn("CONTRADICTORY_SETTLEMENT_COUNT", str(caught.exception))

    def test_fractional_boolean_and_string_counts_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_fixture(root,1,1)
            target=next((root/"settlements").glob("*_PITCHER_K_*.json"))
            for bad in (4.5, True, "3"):
                self._rewrite(target, actual_count=bad, actual_over=True)
                with self.assertRaises(ShadowReadoutError) as caught:
                    readout(root/"predictions", root/"settlements")
                self.assertIn("NONINTEGER_FINAL_COUNT", str(caught.exception))

    def test_nonfinite_and_malformed_settlement_brier_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_fixture(root,1,1)
            target=next((root/"settlements").glob("*.json"))
            for bad in ("0.2", True):
                self._rewrite(target, baseline_brier=bad)
                with self.assertRaises(ShadowReadoutError) as caught:
                    readout(root/"predictions", root/"settlements")
                self.assertIn("MALFORMED_SETTLEMENT_BRIER", str(caught.exception))
            for bad in (float("nan"), float("inf")):
                row=json.loads(target.read_text())
                row["baseline_brier"]=bad
                target.write_text(json.dumps(row, allow_nan=True))
                with self.assertRaises(ShadowReadoutError) as caught:
                    readout(root/"predictions", root/"settlements")
                self.assertIn("NONFINITE_SETTLEMENT_BRIER", str(caught.exception))


if __name__=="__main__":
    unittest.main()
