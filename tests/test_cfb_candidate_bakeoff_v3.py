import json
from hashlib import sha1
from pathlib import Path
from unittest import TestCase

from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_model_v2 import fit_cfb_candidate_score_model
from sportsedge.sports.cfb.candidate_registry_v2 import RELIABILITY
from sportsedge.sports.cfb.reconstructed_selection import materialize_reconstructed_selection_rows
from sportsedge.sports.cfb.source import CFBTeamMetrics
import sportsedge.sports.cfb.candidate_bakeoff_v2 as v2
import sportsedge.sports.cfb.candidate_bakeoff_v3 as v3

ROOT=Path(__file__).resolve().parents[1]


def _blob(path):
    raw=path.read_bytes()
    return sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()


def _metrics(season,value,games=2):
    m={k:float(value + j*0.001) for j,k in enumerate(TEAM_METRIC_KEYS)}
    m.update(team="T",season=season,through_week=2,sample_source="CURRENT_SEASON_PRIOR_WEEKS",games_in_sample=games)
    return m


def _rows(end_season=2018):
    out=[]
    for season in range(2015,end_season+1):
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


def _materializer_metric(team):
    return CFBTeamMetrics(
        team=team,season=2014,through_week=99,sample_source="PRIOR_SEASON_FALLBACK",
        off_ppa_rush=0.1,off_ppa_dropback=0.2,def_ppa_rush_allowed=0.3,
        def_ppa_dropback_allowed=0.4,off_success_rate=0.5,def_success_rate_allowed=0.6,
        standard_down_ppa=0.7,passing_down_success_rate=0.8,eckel_rate=0.9,
        points_per_eckel=1.0,points_per_drive=1.1,net_field_position=1.2,
        explosive_rate=1.3,feature_asof_ts="2026-09-18T12:00:00+00:00",
    )


class TestCFBCandidateBakeoffV3(TestCase):
    def _cfg(self,path,outer=(2018,),grid=(1.0,),shuffles=3):
        cfg=json.loads((ROOT/path).read_text())
        cfg["outer_validation_seasons"]=list(outer)
        cfg["ridge_alpha_grid"]=list(grid)
        cfg["null"]["shuffle_count"]=shuffles
        return cfg

    def test_v3_config_binds_exact_evaluator_and_dependencies(self):
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v3.json").read_text())
        self.assertEqual(_blob(ROOT/cfg["evaluator_path"]),cfg["evaluator_code_git_blob"])
        self.assertEqual(cfg["public_equivalence"]["reference_evaluator_code_git_blob"],"9ebb86a816e42ca07f63ad500fc5a2cd1fe2346a")
        for rel,expected in cfg["dependency_blobs"].items():
            self.assertEqual(_blob(ROOT/rel),expected,rel)
        self.assertFalse(cfg["capture"]["new_mean_fit_allowed"])
        self.assertFalse(cfg["capture"]["capture_in_public_result"])

    def test_v3_public_result_and_hash_are_exactly_v2(self):
        rows=_rows(); identity={"fixture":"V3_EQUIVALENCE_V1"}
        old=v2.evaluate_cfb_candidate_bakeoff_v2(rows,self._cfg("config/cfb_candidate_bakeoff_evaluator_v2.json"),input_identity=identity)
        new,capture=v3.evaluate_cfb_candidate_bakeoff_v3(rows,self._cfg("config/cfb_candidate_bakeoff_evaluator_v3.json"),input_identity=identity)
        self.assertEqual(new,old)
        self.assertEqual(new["result_sha256"],old["result_sha256"])
        self.assertNotIn("capture",new)
        self.assertEqual(capture["capture_pass"],"OBSERVED_UNPERMUTED_ONLY")
        self.assertTrue(all(value is False for value in capture["authority"].values()))

    def test_v3_equivalence_with_multiple_outer_folds_and_alpha_choices(self):
        rows=_rows(2020); identity={"fixture":"V3_MULTI_FOLD_ALPHA_EQUIVALENCE_V1"}
        outer=(2018,2019,2020); grid=(0.1,1.0,10.0)
        old_cfg=self._cfg("config/cfb_candidate_bakeoff_evaluator_v2.json",outer=outer,grid=grid,shuffles=2)
        new_cfg=self._cfg("config/cfb_candidate_bakeoff_evaluator_v3.json",outer=outer,grid=grid,shuffles=2)
        old=v2.evaluate_cfb_candidate_bakeoff_v2(rows,old_cfg,input_identity=identity)
        new,_=v3.evaluate_cfb_candidate_bakeoff_v3(rows,new_cfg,input_identity=identity)
        self.assertEqual(new,old)
        self.assertEqual(new["result_sha256"],old["result_sha256"])
        for family in old["observed"]:
            self.assertEqual(len(old["observed"][family]["folds"]),3)
            self.assertTrue(all(fold["alpha"] in grid for fold in old["observed"][family]["folds"]))

    def test_observed_capture_matches_independent_same_fit_exactly(self):
        rows=_rows()
        score,pred,scored,capture=v3._observed_eval(rows,RELIABILITY,[2018],[1.0])
        fold=capture["folds"][0]
        train=[r for r in rows if int(r["season"])<2018]
        valid=[r for r in rows if int(r["season"])==2018]
        model=fit_cfb_candidate_score_model(train,family=RELIABILITY,ridge_alpha=fold["frozen_alpha"])
        expected_outer=[model.predict_means(r) for r in valid]
        expected_train=[model.predict_means(r) for r in train]

        self.assertEqual(score["folds"][0]["alpha"],1.0)
        self.assertEqual(fold["frozen_alpha"],1.0)
        self.assertEqual(len(pred),len(scored))
        self.assertEqual(pred,expected_outer)
        self.assertEqual(
            [(r["predicted_home_score"],r["predicted_away_score"]) for r in fold["outer_predictions"]],
            expected_outer,
        )
        self.assertEqual(
            [(r["home_residual"],r["away_residual"]) for r in fold["training_residuals"]],
            [(float(r["home_score"])-ph,float(r["away_score"])-pa) for r,(ph,pa) in zip(train,expected_train)],
        )

    def test_capture_identity_accepts_actual_materializer_output_row(self):
        rows=materialize_reconstructed_selection_rows(
            games=[{
                "game_id":"materialized-1","season":2015,"week":1,
                "start_ts":"2015-09-05T17:00:00+00:00","home_team":"Home","away_team":"Away",
                "neutral_site":False,"home_score":31,"away_score":20,
            }],
            metrics=[_materializer_metric("Home"),_materializer_metric("Away")],
            weather_by_game={"materialized-1":{
                "source":"CFBD_GAMES_WEATHER_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE",
                "retrieved_at_utc":"2026-09-18T12:00:00+00:00","gameIndoors":False,
                "windSpeed":8.0,"temperature":72.0,
            }},
            fbs_membership_by_season={2015:[{"school":"Home"},{"school":"Away"}]},
        )
        self.assertEqual(len(rows),1)
        self.assertEqual(v3._id(rows[0]),{"season":2015,"week":1,"game_id":"materialized-1"})


if __name__=="__main__":
    import unittest
    unittest.main()
