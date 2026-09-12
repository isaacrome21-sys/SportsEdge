import unittest
from copy import deepcopy
from hashlib import sha256

from sportsedge.sports.nfl.m2_v2g_forward import canonical_bytes
from sportsedge.sports.nfl.v2g_prospective_evaluation import (
    BINDING_SCHEMA,
    CLV_BUNDLE_SCHEMA,
    CLV_METRIC,
    CLV_ROW_SCHEMA,
    OUTCOME_SCHEMA,
    build_settlement,
    evaluate_checkpoint,
)


class NFLV2GProspectiveEvaluationTests(unittest.TestCase):
    def policy(self):
        return {
            "schema_version":"SPORTSEDGE_NFL_V2G_PROSPECTIVE_EVALUATION_POLICY_V1","status":"FROZEN_BEFORE_FIRST_WEEK2_OUTCOME",
            "outcome_source":{"contract":OUTCOME_SCHEMA,"minimum_hours_after_kickoff":8,"direct_schedule_refetch_for_evaluation":False},
            "eligible_bet":{"minimum_decision_edge":0.03},
            "checkpoints":{"fixed_eligible_bet_counts":[2,3,4],"first_promotion_quality_checkpoint":3},
            "gates":{"mean_clv_min":0.005,"after_vig_roi_min":0.02,"calibration_slope_min":0.9,"calibration_slope_max":1.1,"calibration_intercept_abs_max":0.03,"ece_max":0.025,"max_nonempty_bin_abs_deviation":0.05,"calibration_bins":10},
            "promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False,
        }

    def decision(self):
        common={"prediction_sha256":"b"*64,"artifact_sha256":"c"*64,"model_id":"nfl_m2_scoring_event_v2g_candidate","game_start_ts":"2026-09-20T17:00:00+00:00"}
        return {"game_id":"2026_02_PIT_NE","rows":[
            {**common,"market":"spread","side":"NE","line_at_decision":-3.0,"price_at_decision":-110,"model_prob":0.60,"novig_prob":0.56,"edge":0.04,"ev":0.08,"gate_result":"SHADOW_QUALIFIED"},
            {**common,"market":"total","side":"under","line_at_decision":45.0,"price_at_decision":100,"model_prob":0.55,"novig_prob":0.50,"edge":0.05,"ev":0.10,"gate_result":"SHADOW_QUALIFIED"},
        ]}

    def binding(self):
        ready={"status":"READY_FOR_PROSPECTIVE_EVALUATION"}
        return {
            "schema_version":BINDING_SCHEMA,"status":"READY_FOR_PROSPECTIVE_EVALUATION","game_id":"2026_02_PIT_NE",
            "candidate_id":"nfl_m2_scoring_event_v2g_candidate","market_status":{"spread":ready,"total":ready},
            "prediction":{"prediction_sha256":"b"*64,"artifact_sha256":"c"*64},
            "market_prices_consumed_by_model":False,"promotion_authority":False,"may_create_model_p":False,
            "market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False,
        }

    def clv(self):
        return {"schema_version":CLV_BUNDLE_SCHEMA,"game_id":"2026_02_PIT_NE","rows":[
            {"schema_version":CLV_ROW_SCHEMA,"game_id":"2026_02_PIT_NE","market":"spread","side":"NE","status":"CLV_ELIGIBLE","probability_line":-3.0,"decision_model_prob":0.60,"decision_novig_prob":0.56,"closing_novig_prob":0.57,"clv":0.01},
            {"schema_version":CLV_ROW_SCHEMA,"game_id":"2026_02_PIT_NE","market":"total","side":"under","status":"CLV_ELIGIBLE","probability_line":45.0,"decision_model_prob":0.55,"decision_novig_prob":0.50,"closing_novig_prob":0.52,"clv":0.02},
        ]}

    def outcome(self):
        row={"schema_version":OUTCOME_SCHEMA,"status":"PROSPECTIVE_RESEARCH_OUTCOME_CAPTURED","game_id":"2026_02_PIT_NE","season":2026,"week":2,"kickoff_utc":"2026-09-20T17:00:00+00:00","observed_at_utc":"2026-09-21T01:00:00+00:00","away_team":"PIT","home_team":"NE","away_score":20,"home_score":24,"final_margin_home_minus_away":4,"final_total":44,"prediction_sha256":"b"*64,"artifact_sha256":"c"*64,"prediction_capture_code_git_sha":"d"*40,"settlement_code_git_sha":"e"*40,"result_schedule_snapshot_sha256":"a"*64,"minimum_hours_after_kickoff":8.0,"outcome_source":"NFLVERSE_GAMES_CSV_POSTGAME_SCORE","market_prices_consumed":False,"promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False}
        row["outcome_sha256"]=sha256(canonical_bytes(row)).hexdigest(); return row

    def rehash(self,row):
        row.pop("outcome_sha256",None); row["outcome_sha256"]=sha256(canonical_bytes(row)).hexdigest(); return row

    def test_settlement_requires_full_frozen_evidence_chain(self):
        out=build_settlement(self.decision(),self.binding(),self.clv(),self.outcome(),policy=self.policy())
        self.assertEqual(2,len(out["rows"])); self.assertTrue(all(r["eligible_for_checkpoint"] for r in out["rows"])); self.assertTrue(all(r["clv_metric"]==CLV_METRIC for r in out["rows"])); self.assertEqual("WIN",out["rows"][0]["result"]); self.assertEqual("WIN",out["rows"][1]["result"]); self.assertEqual(self.outcome()["outcome_sha256"],out["outcome_sha256"]); self.assertFalse(out["promotion_authority"])

    def test_missing_market_binding_is_ineligible_not_invented(self):
        out=build_settlement(self.decision(),None,self.clv(),self.outcome(),policy=self.policy()); self.assertTrue(all(not r["eligible_for_checkpoint"] for r in out["rows"])); self.assertTrue(all("PAIRED_MARKET_BINDING_NOT_READY" in r["ineligibility_reasons"] for r in out["rows"]))

    def test_market_binding_must_match_game_prediction_and_artifact(self):
        bad=deepcopy(self.binding()); bad["game_id"]="2026_02_X_Y"
        with self.assertRaisesRegex(ValueError,"BINDING_GAME_MISMATCH"): build_settlement(self.decision(),bad,self.clv(),self.outcome(),policy=self.policy())
        bad=deepcopy(self.binding()); bad["prediction"]["prediction_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"BINDING_PREDICTION_MISMATCH"): build_settlement(self.decision(),bad,self.clv(),self.outcome(),policy=self.policy())
        bad=deepcopy(self.binding()); bad["prediction"]["artifact_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"BINDING_ARTIFACT_MISMATCH"): build_settlement(self.decision(),bad,self.clv(),self.outcome(),policy=self.policy())

    def test_canonical_outcome_cannot_be_early_or_tampered(self):
        early=self.outcome(); early["observed_at_utc"]="2026-09-20T20:00:00+00:00"; self.rehash(early)
        with self.assertRaisesRegex(ValueError,"OUTCOME_TOO_EARLY"): build_settlement(self.decision(),self.binding(),self.clv(),early,policy=self.policy())
        tampered=self.outcome(); tampered["home_score"]=30
        with self.assertRaisesRegex(ValueError,"OUTCOME_SHA_MISMATCH"): build_settlement(self.decision(),self.binding(),self.clv(),tampered,policy=self.policy())

    def test_canonical_outcome_must_bind_prediction_and_artifact(self):
        wrong=self.outcome(); wrong["prediction_sha256"]="f"*64; self.rehash(wrong)
        with self.assertRaisesRegex(ValueError,"OUTCOME_PREDICTION_MISMATCH"): build_settlement(self.decision(),self.binding(),self.clv(),wrong,policy=self.policy())
        wrong=self.outcome(); wrong["artifact_sha256"]="f"*64; self.rehash(wrong)
        with self.assertRaisesRegex(ValueError,"OUTCOME_ARTIFACT_MISMATCH"): build_settlement(self.decision(),self.binding(),self.clv(),wrong,policy=self.policy())

    def test_stale_model_minus_close_clv_formula_is_rejected(self):
        stale=deepcopy(self.clv()); stale["rows"][0]["clv"]=0.03
        with self.assertRaisesRegex(ValueError,"CLV_METRIC_MISMATCH"): build_settlement(self.decision(),self.binding(),stale,self.outcome(),policy=self.policy())

    def test_clv_must_bind_same_decision_novig_and_side(self):
        stale=deepcopy(self.clv()); stale["rows"][0]["decision_novig_prob"]=0.55; stale["rows"][0]["clv"]=0.02
        with self.assertRaisesRegex(ValueError,"CLV_DECISION_NOVIG_MISMATCH"): build_settlement(self.decision(),self.binding(),stale,self.outcome(),policy=self.policy())
        wrong_side=deepcopy(self.clv()); wrong_side["rows"][0]["side"]="PIT"
        with self.assertRaisesRegex(ValueError,"CLV_SIDE_MISMATCH"): build_settlement(self.decision(),self.binding(),wrong_side,self.outcome(),policy=self.policy())

    def test_checkpoint_uses_frozen_prefix_only(self):
        rows=[]
        for idx,(p,result,clv,profit) in enumerate([(0.4,"LOSS",0.01,-1.0),(0.6,"WIN",0.02,1.0),(0.7,"WIN",-0.5,-1.0)]): rows.append({"game_id":f"2026_02_X{idx}_Y{idx}","kickoff_utc":f"2026-09-{20+idx:02d}T17:00:00+00:00","rows":[{"market":"spread","model_prob":p,"result":result,"clv":clv,"clv_metric":CLV_METRIC,"profit_units":profit,"eligible_for_checkpoint":True}]})
        report=evaluate_checkpoint(rows,count=2,policy=self.policy()); self.assertEqual(2,report["checkpoint_count"]); self.assertEqual([["2026_02_X0_Y0","spread"],["2026_02_X1_Y1","spread"]],report["row_identity"]); self.assertEqual("CHECKPOINT_DIAGNOSTIC_ONLY",report["status"]); self.assertAlmostEqual(0.015,report["metrics"]["mean_clv"]); self.assertEqual(CLV_METRIC,report["metrics"]["clv_metric"]); self.assertFalse(report["promotion_authority"])

    def test_checkpoint_rejects_legacy_unbound_clv_metric(self):
        rows=[{"game_id":"2026_02_X0_Y0","kickoff_utc":"2026-09-20T17:00:00+00:00","rows":[{"market":"spread","model_prob":0.6,"result":"WIN","clv":0.01,"profit_units":1.0,"eligible_for_checkpoint":True}]}]
        with self.assertRaisesRegex(ValueError,"CHECKPOINT_CLV_METRIC_INVALID"): evaluate_checkpoint(rows,count=1,policy=self.policy())


if __name__=="__main__": unittest.main()
