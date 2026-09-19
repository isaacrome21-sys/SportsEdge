import json
from hashlib import sha1
from pathlib import Path
from unittest import TestCase, mock

import sportsedge.sports.cfb.candidate_bakeoff_v2 as v2

ROOT=Path(__file__).resolve().parents[1]

class TestCFBCandidateBakeoffV2(TestCase):
    def test_v2_freeze_binds_exact_evaluator_and_attempts_remain_zero(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v2.json").read_text())
        raw=(ROOT/cfg["evaluator_path"]).read_bytes()
        actual=sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()
        self.assertEqual(actual,cfg["evaluator_code_git_blob"])
        self.assertEqual(cfg["null"]["refit_rule"],"REFIT_AND_RESCORE_EVERY_PREREGISTERED_CANDIDATE_ON_EACH_SHUFFLE")
        policy=json.loads((ROOT/"config/cfb_model_selection_policy_v1.json").read_text())
        prereg=json.loads((ROOT/"config/cfb_model_candidate_prereg_v1.json").read_text())
        self.assertEqual(policy["attempts_consumed"],0)
        self.assertEqual(prereg["governance"]["attempts_consumed"],0)
        self.assertFalse(prereg["governance"]["evaluation_performed"])

    def test_each_null_shuffle_refits_and_rescores_all_four_families(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v2.json").read_text())
        cfg["outer_validation_seasons"]=[2018]
        cfg["null"]["shuffle_count"]=3
        rows=[
            {"season":2018,"home_score":20+i,"away_score":10+i,
             "regulation_home_score":20+i,"regulation_away_score":10+i}
            for i in range(4)
        ]
        calls=[]
        def fake_eval(data,family,outer,grid):
            calls.append((family,tuple((r["home_score"],r["away_score"]) for r in data)))
            pred=[(float(r["home_score"]),float(r["away_score"])) for r in data]
            return {"selection_metric":1.0,"folds":[]},pred,data
        with mock.patch.object(v2,"_candidate_eval",side_effect=fake_eval):
            out=v2.evaluate_cfb_candidate_bakeoff_v2(rows,cfg,input_identity={"test":"refit"})
        self.assertEqual(len(calls),4 + 3*4)
        for start in (4,8,12):
            self.assertEqual({family for family,_ in calls[start:start+4]},set(v2.FAMILIES))
        self.assertTrue(out["null"]["refit_and_rescore_every_candidate_each_shuffle"])
        self.assertTrue(all(value is False for value in out["authority"].values()))
