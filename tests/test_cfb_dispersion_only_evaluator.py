import json
from pathlib import Path
from unittest import TestCase, mock

import numpy as np

from sportsedge.sports.cfb.candidate_bakeoff import _hash
from sportsedge.sports.cfb.joint_model import _TEAM_KEYS, fit_cfb_joint_score_model
from sportsedge.sports.cfb.joint_model_v2_challenger import fit_cfb_v2_challenger, simulate_cfb_v2_paths
import sportsedge.sports.cfb.dispersion_only_evaluator as de

ROOT=Path(__file__).resolve().parents[1]


def _model_rows(seasons, n=80, seed=17):
    rng=np.random.default_rng(seed); out=[]
    for season in seasons:
        for g in range(n):
            oh,oa=rng.normal(0,1,2)
            hm={k:float(rng.normal(0,0.3)) for k in _TEAM_KEYS}; am={k:float(rng.normal(0,0.3)) for k in _TEAM_KEYS}
            hm["points_per_drive"]+=oh; am["points_per_drive"]+=oa
            mh,ma=30+7*oh,27+7*oa
            h=max(0,int(round(mh+np.sqrt(max(mh,4))*2*rng.normal())))
            a=max(0,int(round(ma+np.sqrt(max(ma,4))*2*rng.normal())))
            row={"game_id":f"{season}-{g}","season":season,"week":1+(g%12),"neutral_site":False,
                 "home_metrics":hm,"away_metrics":am,"weather":{"game_indoor":True},"home_score":h,"away_score":a}
            if g==0:
                row.update(regulation_home_score=21,regulation_away_score=21,home_score=28,away_score=21)
            elif h==a:
                row.update(regulation_home_score=h,regulation_away_score=a,home_score=h+7)
            out.append(row)
    return out


def _reference_folds(rows, seasons, alpha=10.0):
    folds={}
    for season in seasons:
        tr=[r for r in rows if int(r["season"])<season]
        va=[r for r in rows if int(r["season"])==season]
        model=fit_cfb_joint_score_model(tr,ridge_alpha=alpha)
        outer=[]
        for r in va:
            ph,pa=model.predict_means(r)
            outer.append({"season":season,"week":r["week"],"game_id":r["game_id"],
                          "predicted_home_score":ph,"predicted_away_score":pa,
                          "realized_home_score":float(r["home_score"]),"realized_away_score":float(r["away_score"])})
        folds[season]={"outer_season":season,"outer_predictions":outer,"training_residuals":[]}
    return folds


def _governed_fixture(n=100):
    rows=[]
    for season in range(2015,2026):
        for g in range(n):
            h=24+((g+season)%12); a=17+((2*g+season)%10)
            row={"game_id":f"{season}-{g:03d}","season":season,"week":1+(g%12),"home_score":h,"away_score":a}
            if g==0:
                row.update(regulation_home_score=21,regulation_away_score=21,home_score=28,away_score=21)
            rows.append(row)
    folds=[]
    for season in range(2018,2026):
        train=[r for r in rows if r["season"]<season]
        valid=[r for r in rows if r["season"]==season]
        folds.append({
            "outer_season":season,
            "frozen_alpha":1.0,
            "outer_predictions":[{
                "season":r["season"],"week":r["week"],"game_id":r["game_id"],
                "predicted_home_score":27.0+0.02*(int(r["week"])-1),
                "predicted_away_score":21.0+0.01*(int(r["week"])-1),
                "realized_home_score":float(r["home_score"]),"realized_away_score":float(r["away_score"]),
            } for r in valid],
            "training_residuals":[{
                "season":r["season"],"week":r["week"],"game_id":r["game_id"],
                "home_residual":float(r["home_score"])-27.0,
                "away_residual":float(r["away_score"])-21.0,
            } for r in train],
        })
    winner="RELIABILITY_WEIGHTED_HARD_SWITCH"
    result={
        "schema":"CFB_CANDIDATE_BAKEOFF_RESULT_V2","status":"WINNER_SELECTED_FOR_FREEZE","winner":winner,
        "rows_sha256":_hash(rows),"input_identity":{"fixture":"dispersion"},
        "authority":{"model_p_created":False,"truth_gate_authority":False,"promotion_authority":False,
                     "eligibility_changed":False,"staking_authority":False,"evidence_clock_authority":False,
                     "backfill":False,"official_authority":False},
    }
    result["result_sha256"]=_hash(result)
    capture={
        "schema":"CFB_CANDIDATE_BAKEOFF_PRIVATE_CAPTURE_V1","status":"WINNER_CAPTURE_RETAINED",
        "capture_pass":"OBSERVED_UNPERMUTED_ONLY","captured_families_during_run":[winner],
        "retained_family":winner,"winner_capture":{"family":winner,"folds":folds},
        "authority":{"model_p_created":False,"truth_gate_authority":False,"promotion_authority":False,
                     "eligibility_changed":False,"staking_authority":False,"evidence_clock_authority":False,
                     "backfill":False,"official_authority":False},
    }
    capture["capture_sha256"]=_hash(capture)
    return rows,result,capture


class TestCFBDispersionOnlyEvaluator(TestCase):
    def test_ranked_probability_score_definition(self):
        self.assertAlmostEqual(de.ranked_probability_score(np.asarray([0,1,2]),1),2.0/9.0)

    def test_v2_capture_simulation_matches_reference_module_bit_for_bit(self):
        rows=_model_rows((2017,2018,2019,2020))
        reference=fit_cfb_v2_challenger(rows,ridge_alpha=10.0)
        folds=_reference_folds(rows,(2018,2019,2020),alpha=10.0)
        state=de.build_v2_capture_state(folds,2021)
        test_row=rows[-1]
        mh,ma=reference.predict_means(test_row)
        ot=de._overtime_profile(rows,2021)
        expected=simulate_cfb_v2_paths(reference,test_row,seed=12345,n_paths=2000)
        actual=de.simulate_v2_capture_paths(mh,ma,state,ot,seed=12345,n_paths=2000)
        self.assertTrue(np.array_equal(expected[0],actual[0]))
        self.assertTrue(np.array_equal(expected[1],actual[1]))

    def test_full_evaluation_consumes_capture_without_refitting(self):
        rows,result,capture=_governed_fixture()
        source=(ROOT/"sportsedge/sports/cfb/dispersion_only_evaluator.py").read_text()
        self.assertNotIn("fit_cfb_candidate_score_model",source)
        self.assertNotIn("fit_cfb_joint_score_model",source)
        with mock.patch.object(de,"N_PATHS",20), mock.patch.object(de,"BOOTSTRAP_RESAMPLES",20):
            out=de.evaluate_cfb_dispersion_only(rows,result,capture)
        self.assertEqual(out["n_games"],700)
        self.assertEqual(out["n_paths_per_game_per_model"],20)
        self.assertEqual(out["capture_sha256"],capture["capture_sha256"])
        self.assertIn(out["status"],{"V2_DEMONSTRATED_DISPERSION_IMPROVEMENT_DIAGNOSTIC_ONLY","NO_DEMONSTRATED_DISPERSION_IMPROVEMENT"})
        self.assertTrue(all(v is False for v in out["authority"].values()))

    def test_tampered_capture_hash_fails_closed(self):
        rows,result,capture=_governed_fixture()
        capture["winner_capture"]["folds"][0]["frozen_alpha"]=999.0
        with self.assertRaisesRegex(de.CFBDispersionEvaluationError,"CAPTURE_HASH_INVALID"):
            de.evaluate_cfb_dispersion_only(rows,result,capture)

    def test_missing_required_capture_row_fails_whole_run(self):
        rows,result,capture=_governed_fixture()
        capture["winner_capture"]["folds"][1]["outer_predictions"].pop()
        capture.pop("capture_sha256")
        capture["capture_sha256"]=_hash(capture)
        with self.assertRaisesRegex(de.CFBDispersionEvaluationError,"CAPTURE_ROW_SET_MISMATCH"):
            de.evaluate_cfb_dispersion_only(rows,result,capture)

    def test_null_bakeoff_does_not_run(self):
        rows,result,capture=_governed_fixture()
        result.pop("result_sha256"); result["status"]="NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"; result["winner"]=None
        result["result_sha256"]=_hash(result)
        with self.assertRaisesRegex(de.CFBDispersionEvaluationError,"PARENT_WINNER_REQUIRED"):
            de.evaluate_cfb_dispersion_only(rows,result,capture)


if __name__=="__main__":
    import unittest
    unittest.main()
