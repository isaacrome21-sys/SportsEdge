import json
from hashlib import sha1
from pathlib import Path
from unittest import TestCase

from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_registry_v2 import RELIABILITY
import sportsedge.sports.cfb.candidate_bakeoff_v2 as v2
import sportsedge.sports.cfb.candidate_bakeoff_v3 as v3

ROOT=Path(__file__).resolve().parents[1]


def _metrics(season,value,games=2):
    m={k:float(value + j*0.001) for j,k in enumerate(TEAM_METRIC_KEYS)}
    m.update(team="T",season=season,through_week=2,sample_source="CURRENT_SEASON_PRIOR_WEEKS",games_in_sample=games)
    return m


def _rows():
    out=[]
    for season in range(2015,2019):
        for i in range(10):
            hv=0.1 + (season-2015)*0.03 + i*0.01
            av=0.08 + (season-2015)*0.02 + i*0.008
            hp=_metrics(season-1,hv-0.04); ap=_metrics(season-1,av-0.04)
            hp.update(through_week=99,sample_source="PRIOR_SEASON_FALLBACK",games_in_sample=0)
            ap.update(through_week=99,sample_source="PRIOR_SEASON_FALLBACK",games_in_sample=0)
            hc=_metrics(season,hv); ac=_metrics(season,av)
            out.append({
                "game_id":f"{season}-{i}","season":season,"week":3,"neutral_site":False,
                "weather":{"game_indoor":True},"home_metrics":hc.copy(),"away_metrics":ac.copy(),
                "home_prior_metrics":hp,"away_prior_metrics":ap,"home_current_metrics":hc,"away_current_metrics":ac,
                "home_score":24 + (i%5) + (season-2015),"away_score":17 + (i%4),
            })
    return out


class TestCFBCandidateBakeoffV3(TestCase):
    def _small_cfg(self,path):
        cfg=json.loads((ROOT/path).read_text())
        cfg["outer_validation_seasons"]=[2018]
        cfg["ridge_alpha_grid"]=[1.0]
        cfg["null"]["shuffle_count"]=3
        return cfg

    def test_v3_config_binds_exact_evaluator(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v3.json").read_text())
        raw=(ROOT/cfg["evaluator_path"]).read_bytes()
        actual=sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()
        self.assertEqual(actual,cfg["evaluator_code_git_blob"])
        self.assertEqual(cfg["public_equivalence"]["reference_evaluator_code_git_blob"],"9ebb86a816e42ca07f63ad500fc5a2cd1fe2346a")
        self.assertFalse(cfg["capture"]["new_mean_fit_allowed"])
        self.assertFalse(cfg["capture"]["capture_in_public_result"])

    def test_v3_public_result_and_hash_are_exactly_v2(self):
        rows=_rows(); identity={"fixture":"V3_EQUIVALENCE_V1"}
        old=v2.evaluate_cfb_candidate_bakeoff_v2(rows,self._small_cfg("config/cfb_candidate_bakeoff_evaluator_v2.json"),input_identity=identity)
        new,capture=v3.evaluate_cfb_candidate_bakeoff_v3(rows,self._small_cfg("config/cfb_candidate_bakeoff_evaluator_v3.json"),input_identity=identity)
        self.assertEqual(new,old)
        self.assertEqual(new["result_sha256"],old["result_sha256"])
        self.assertNotIn("capture",new)
        self.assertEqual(capture["capture_pass"],"OBSERVED_UNPERMUTED_ONLY")
        self.assertTrue(all(value is False for value in capture["authority"].values()))

    def test_observed_capture_uses_same_fold_fit(self):
        rows=_rows()
        score,pred,scored,capture=v3._observed_eval(rows,RELIABILITY,[2018],[1.0])
        self.assertEqual(score["folds"][0]["alpha"],1.0)
        self.assertEqual(capture["folds"][0]["frozen_alpha"],1.0)
        self.assertEqual(len(capture["folds"][0]["outer_predictions"]),10)
        self.assertEqual(len(capture["folds"][0]["training_residuals"]),30)
        self.assertEqual(len(pred),len(scored))
        self.assertEqual(len(pred),10)


if __name__=="__main__":
    import unittest
    unittest.main()
