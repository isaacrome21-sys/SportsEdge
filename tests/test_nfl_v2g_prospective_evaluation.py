import unittest
from copy import deepcopy
from datetime import datetime, timezone

from sportsedge.sports.nfl.v2g_prospective_evaluation import (
    CLV_BUNDLE_SCHEMA,
    CLV_METRIC,
    CLV_ROW_SCHEMA,
    build_settlement,
    evaluate_checkpoint,
)


class NFLV2GProspectiveEvaluationTests(unittest.TestCase):
    def policy(self):
        return {
            "schema_version":"SPORTSEDGE_NFL_V2G_PROSPECTIVE_EVALUATION_POLICY_V1","status":"FROZEN_BEFORE_FIRST_WEEK2_OUTCOME",
            "outcome_source":{"minimum_hours_after_kickoff":6},
            "eligible_bet":{"minimum_decision_edge":0.03},
            "checkpoints":{"fixed_eligible_bet_counts":[2,3,4],"first_promotion_quality_checkpoint":3},
            "gates":{"mean_clv_min":0.005,"after_vig_roi_min":0.02,"calibration_slope_min":0.9,"calibration_slope_max":1.1,"calibration_intercept_abs_max":0.03,"ece_max":0.025,"max_nonempty_bin_abs_deviation":0.05,"calibration_bins":10},
            "promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False,
        }

    def decision(self):
        return {"game_id":"2026_02_PIT_NE","rows":[
            {"market":"spread","side":"NE","line_at_decision":-3.0,"price_at_decision":-110,"model_prob":0.60,"novig_prob":0.56,"edge":0.04,"ev":0.08,"gate_result":"SHADOW_QUALIFIED","game_start_ts":"2026-09-20T17:00:00+00:00"},
            {"market":"total","side":"under","line_at_decision":45.0,"price_at_decision":100,"model_prob":0.55,"novig_prob":0.50,"edge":0.05,"ev":0.10,"gate_result":"SHADOW_QUALIFIED","game_start_ts":"2026-09-20T17:00:00+00:00"},
        ]}

    def binding(self):
        ready={"status":"READY_FOR_PROSPECTIVE_EVALUATION"}
        return {"market_status":{"spread":ready,"total":ready}}

    def clv(self):
        return {"schema_version":CLV_BUNDLE_SCHEMA,"game_id":"2026_02_PIT_NE","rows":[
            {"schema_version":CLV_ROW_SCHEMA,"game_id":"2026_02_PIT_NE","market":"spread","side":"NE","status":"CLV_ELIGIBLE","probability_line":-3.0,"decision_model_prob":0.60,"decision_novig_prob":0.56,"closing_novig_prob":0.57,"clv":0.01},
            {"schema_version":CLV_ROW_SCHEMA,"game_id":"2026_02_PIT_NE","market":"total","side":"under","status":"CLV_ELIGIBLE","probability_line":45.0,"decision_model_prob":0.55,"decision_novig_prob":0.50,"closing_novig_prob":0.52,"clv":0.02},
        ]}

    def outcome(self):
        return {"game_id":"2026_02_PIT_NE","away_team":"PIT","home_team":"NE","away_score":"20","home_score":"24"}

    def test_settlement_requires_full_frozen_evidence_chain(self):
        out=build_settlement(self.decision(),self.binding(),self.clv(),self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,21,1,tzinfo=timezone.utc),policy=self.policy())
        self.assertEqual(2,len(out["rows"]))
        self.assertTrue(all(r["eligible_for_checkpoint"] for r in out["rows"]))
        self.assertTrue(all(r["clv_metric"]==CLV_METRIC for r in out["rows"]))
        self.assertEqual("WIN",out["rows"][0]["result"])
        self.assertEqual("WIN",out["rows"][1]["result"])
        self.assertFalse(out["promotion_authority"])

    def test_missing_market_binding_is_ineligible_not_invented(self):
        out=build_settlement(self.decision(),None,self.clv(),self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,21,1,tzinfo=timezone.utc),policy=self.policy())
        self.assertTrue(all(not r["eligible_for_checkpoint"] for r in out["rows"]))
        self.assertTrue(all("PAIRED_MARKET_BINDING_NOT_READY" in r["ineligibility_reasons"] for r in out["rows"]))

    def test_outcome_cannot_settle_too_early(self):
        with self.assertRaisesRegex(ValueError,"OUTCOME_TOO_EARLY"):
            build_settlement(self.decision(),self.binding(),self.clv(),self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,20,20,tzinfo=timezone.utc),policy=self.policy())

    def test_stale_model_minus_close_clv_formula_is_rejected(self):
        stale=deepcopy(self.clv())
        stale["rows"][0]["clv"]=0.03
        with self.assertRaisesRegex(ValueError,"CLV_METRIC_MISMATCH"):
            build_settlement(self.decision(),self.binding(),stale,self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,21,1,tzinfo=timezone.utc),policy=self.policy())

    def test_clv_must_bind_same_decision_novig_and_side(self):
        stale=deepcopy(self.clv())
        stale["rows"][0]["decision_novig_prob"]=0.55
        stale["rows"][0]["clv"]=0.02
        with self.assertRaisesRegex(ValueError,"CLV_DECISION_NOVIG_MISMATCH"):
            build_settlement(self.decision(),self.binding(),stale,self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,21,1,tzinfo=timezone.utc),policy=self.policy())

        wrong_side=deepcopy(self.clv())
        wrong_side["rows"][0]["side"]="PIT"
        with self.assertRaisesRegex(ValueError,"CLV_SIDE_MISMATCH"):
            build_settlement(self.decision(),self.binding(),wrong_side,self.outcome(),outcome_snapshot_sha256="a"*64,observed_at=datetime(2026,9,21,1,tzinfo=timezone.utc),policy=self.policy())

    def test_checkpoint_uses_frozen_prefix_only(self):
        rows=[]
        for idx,(p,result,clv,profit) in enumerate([(0.4,"LOSS",0.01,-1.0),(0.6,"WIN",0.02,1.0),(0.7,"WIN",-0.5,-1.0)]):
            rows.append({"game_id":f"2026_02_X{idx}_Y{idx}","kickoff_utc":f"2026-09-{20+idx:02d}T17:00:00+00:00","rows":[{"market":"spread","model_prob":p,"result":result,"clv":clv,"clv_metric":CLV_METRIC,"profit_units":profit,"eligible_for_checkpoint":True}]})
        report=evaluate_checkpoint(rows,count=2,policy=self.policy())
        self.assertEqual(2,report["checkpoint_count"])
        self.assertEqual([["2026_02_X0_Y0","spread"],["2026_02_X1_Y1","spread"]],report["row_identity"])
        self.assertEqual("CHECKPOINT_DIAGNOSTIC_ONLY",report["status"])
        self.assertAlmostEqual(0.015,report["metrics"]["mean_clv"])
        self.assertEqual(CLV_METRIC,report["metrics"]["clv_metric"])
        self.assertFalse(report["promotion_authority"])

    def test_checkpoint_rejects_legacy_unbound_clv_metric(self):
        rows=[{"game_id":"2026_02_X0_Y0","kickoff_utc":"2026-09-20T17:00:00+00:00","rows":[{"market":"spread","model_prob":0.6,"result":"WIN","clv":0.01,"profit_units":1.0,"eligible_for_checkpoint":True}]}]
        with self.assertRaisesRegex(ValueError,"CHECKPOINT_CLV_METRIC_INVALID"):
            evaluate_checkpoint(rows,count=1,policy=self.policy())


if __name__=="__main__": unittest.main()
