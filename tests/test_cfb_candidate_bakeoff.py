import json
from hashlib import sha1
from pathlib import Path
import unittest

from sportsedge.sports.cfb.candidate_bakeoff import evaluate_cfb_candidate_bakeoff
from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS

ROOT=Path(__file__).resolve().parents[1]

class TestCFBCandidateBakeoff(unittest.TestCase):
    def test_frozen_config_binds_exact_evaluator_blob(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v1.json").read_text())
        raw=(ROOT/cfg["evaluator_path"]).read_bytes()
        actual=sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()
        self.assertEqual(actual,cfg["evaluator_code_git_blob"])
        self.assertEqual(cfg["outer_validation_seasons"],list(range(2018,2026)))
        self.assertEqual(cfg["null"]["shuffle_count"],200)
        self.assertEqual(cfg["null"]["seed"],20260919)
        self.assertEqual(cfg["null"]["percentile_method"],"higher")
        self.assertTrue(cfg["null"]["strict_exceedance"])

    def test_full_four_family_smoke_keeps_authority_zero(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v1.json").read_text())
        rows=[]
        for season in range(2015,2026):
            for i in range(12):
                def m(s,source,through,games,shift):
                    d={k:0.05*(j+1)+shift+0.01*(season-2015) for j,k in enumerate(TEAM_METRIC_KEYS)}
                    d.update(season=s,through_week=through,sample_source=source,games_in_sample=games)
                    return d
                hp=m(season-1,"PRIOR_SEASON_FALLBACK",99,12,0.02)
                ap=m(season-1,"PRIOR_SEASON_FALLBACK",99,12,-0.02)
                hc=m(season,"CURRENT_SEASON_PRIOR_WEEKS",1,1,0.03)
                ac=m(season,"CURRENT_SEASON_PRIOR_WEEKS",1,1,-0.03)
                rows.append({"game_id":f"{season}-{i}","season":season,"week":2,"neutral_site":False,
                    "home_prior_metrics":hp,"away_prior_metrics":ap,
                    "home_current_metrics":hc,"away_current_metrics":ac,
                    "home_metrics":hc,"away_metrics":ac,
                    "weather":{"game_indoor":True},
                    "home_score":24+(i%5)+(season%3),"away_score":17+(i%4),
                    "regulation_home_score":24+(i%5)+(season%3),"regulation_away_score":17+(i%4)})
        out=evaluate_cfb_candidate_bakeoff(rows,cfg,input_identity={"test":"synthetic"})
        self.assertEqual(set(out["observed"]),set(cfg["candidate_families"]))
        self.assertIn(out["status"],{"WINNER_SELECTED_FOR_FREEZE","NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"})
        self.assertEqual(len(out["result_sha256"]),64)
        self.assertTrue(all(v is False for v in out["authority"].values()))

if __name__=="__main__":
    unittest.main()
