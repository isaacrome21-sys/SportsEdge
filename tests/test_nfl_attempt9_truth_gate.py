import unittest

from sportsedge.sports.nfl.attempt9_model_p import (
    CALIBRATION_CONTRACT,CANDIDATE_ID,MODEL_P_ID,MODEL_P_SCHEMA,MODEL_P_STATUS,
    canonical_sha256 as artifact_sha,
)
from sportsedge.sports.nfl.attempt9_prospective import build_decision
from sportsedge.sports.nfl.attempt9_prospective_evidence import build_evidence
from sportsedge.sports.nfl.attempt9_truth_gate import evaluate_truth_gate


class NFLAttempt9TruthGateTests(unittest.TestCase):
    def artifact(self):
        a={"schema_version":MODEL_P_SCHEMA,"status":MODEL_P_STATUS,"model_p_id":MODEL_P_ID,
          "candidate_id":CANDIDATE_ID,"code_git_sha":"1"*40,"runtime_artifact_sha256":"a"*64,
          "source_sha256":"b"*64,"calibration_fit":{"contract":CALIBRATION_CONTRACT,
          "seasons":[2017,2018,2019],"role":"SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE"},
          "markets":{"spread":{"sigma":13.8,"calibration_blocks":[{"lo":0,"hi":1,"weight":500,"mean":0.60}]},
          "total":{"sigma":14,"calibration_blocks":[{"lo":0,"hi":1,"weight":500,"mean":0.60}]}},
          "authority":{"creates_model_p":True,"historical_fit_promotion_authority":False,"deployed":False,
          "truth_gate_pass":False,"official_authority":False,"staking_authority":False}}
        a["artifact_sha256"]=artifact_sha(a); return a

    def governance(self):
        return {"nfl_game_market_precommitted_thresholds":{
          "minimum_model_edge_probability_points":.03,"minimum_mean_clv_probability_points":.005,
          "minimum_clv_t_stat":2.0,"minimum_after_vig_roi":.02,"minimum_promoted_decisions":200,
          "minimum_distinct_week_clusters":12,"calibration_slope_min":.90,"calibration_slope_max":1.10,
          "calibration_intercept_abs_max":.03,"ece_max":.025,"max_nonempty_bin_deviation":.05}}

    def pair(self, game_id="2026_03_A_B", market="spread", capture_sha="c"*40):
        a=self.artifact()
        d=build_decision(artifact=a,game_id=game_id,kickoff_utc="2026-09-27T20:00:00Z",
          decision_at_utc="2026-09-27T18:00:00Z",feature_asof_utc="2026-09-27T17:30:00Z",
          quote_observed_at_utc="2026-09-27T17:59:00Z",capture_code_git_sha=capture_sha,
          book="draftkings",quote_sha256="d"*64,market=market,selection="home" if market=="spread" else "over",line=-3.5 if market=="spread" else 40.5,
          price_american=-110,opposite_price_american=-110,raw_prediction=6)
        e=build_evidence(d,artifact=a,closing_quote_at_utc="2026-09-27T19:40:00Z",
          closing_book="draftkings",closing_line=-3.5 if market=="spread" else 40.5,closing_price_american=-130,
          closing_opposite_price_american=110,closing_quote_sha256="e"*64,
          settled_at_utc="2026-09-27T23:30:00Z",home_score=27,away_score=20,
          settlement_source_sha256="f"*64)
        return a,d,e

    def test_underpowered_sample_is_blocked_even_with_external_attestations(self):
        a,d,e=self.pair()
        out=evaluate_truth_gate([d],[e],artifact=a,governance=self.governance(),
          ci_attested=True,pit_integrity_verified=True,truth_gate_floor_verified=True)
        self.assertEqual("BLOCKED",out["status"])
        self.assertFalse(out["checks"]["minimum_promoted_decisions"])
        self.assertFalse(out["checks"]["minimum_distinct_week_clusters"])
        self.assertFalse(out["promotion_authority"]); self.assertFalse(out["official_authority"])

    def test_external_attestations_are_hard_gates(self):
        a,d,e=self.pair()
        out=evaluate_truth_gate([d],[e],artifact=a,governance=self.governance(),
          ci_attested=False,pit_integrity_verified=False,truth_gate_floor_verified=False)
        self.assertFalse(out["checks"]["ci_attested"])
        self.assertFalse(out["checks"]["pit_integrity_verified"])
        self.assertFalse(out["checks"]["truth_gate_floor_verified"])
        self.assertEqual("BLOCKED",out["status"])

    def test_orphan_evidence_fails_closed(self):
        a,d,e=self.pair()
        with self.assertRaisesRegex(ValueError,"ORPHAN_EVIDENCE"):
            evaluate_truth_gate([], [e], artifact=a, governance=self.governance(),
              ci_attested=True,pit_integrity_verified=True,truth_gate_floor_verified=True)

    def test_duplicate_decision_fails_closed(self):
        a,d,e=self.pair()
        with self.assertRaisesRegex(ValueError,"DUPLICATE_DECISION"):
            evaluate_truth_gate([d,d],[e],artifact=a,governance=self.governance(),
              ci_attested=True,pit_integrity_verified=True,truth_gate_floor_verified=True)

    def evaluate(self, decisions, evidence):
        return evaluate_truth_gate(decisions, evidence, artifact=self.artifact(),
            governance=self.governance(), ci_attested=True,
            pit_integrity_verified=True, truth_gate_floor_verified=True)

    def test_duplicate_evidence_cannot_inflate_sample(self):
        _,d,e=self.pair()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EVIDENCE"):
            self.evaluate([d], [e,e])

    def test_markets_cannot_pool_sample_size(self):
        _,d,e=self.pair()
        _,other,close=self.pair(market="total")
        with self.assertRaisesRegex(ValueError, "MIXED_MARKETS"):
            self.evaluate([d,other], [e,close])

    def test_missing_evidence_stays_in_denominator(self):
        _,d,e=self.pair()
        _,missing,_=self.pair(game_id="2026_03_C_D")
        out=self.evaluate([d,missing], [e])
        self.assertEqual(out["submitted_decisions"], 2)
        self.assertEqual(out["missing_evidence_decisions"], 1)
        self.assertEqual(out["evidence_coverage"], .5)
        self.assertFalse(out["checks"]["complete_evidence_coverage"])
        self.assertEqual(out["status"], "BLOCKED")

    def test_unpaired_identity_drift_is_rejected(self):
        _,d,e=self.pair()
        _,missing,_=self.pair(game_id="2026_03_C_D", capture_sha="a"*40)
        with self.assertRaisesRegex(ValueError, "IDENTITY_DRIFT"):
            self.evaluate([d,missing], [e])

    def test_constant_positive_clv_cannot_pass_t_stat(self):
        _,d,e=self.pair()
        _,other,close=self.pair(game_id="2026_04_C_D")
        out=self.evaluate([d,other], [e,close])
        self.assertGreater(out["mean_clv"], 0)
        self.assertFalse(out["checks"]["minimum_clv_t_stat"])
        self.assertFalse(out["checks"]["inference_policy_resolved"])

    def test_roi_rejects_unknown_and_push_outcomes(self):
        from sportsedge.sports.nfl.attempt9_truth_gate import _roi
        for outcome in ("PUSH", "VOID", "UNKNOWN", ""):
            with self.assertRaisesRegex(ValueError, "OUTCOME_UNSUPPORTED"):
                _roi(-110, outcome)

    def test_same_game_market_selection_counts_earliest_valid_capture_once(self):
        a,early,early_evidence=self.pair()
        later=build_decision(
          artifact=a,game_id="2026_03_A_B",kickoff_utc="2026-09-27T20:00:00Z",
          decision_at_utc="2026-09-27T18:30:00Z",feature_asof_utc="2026-09-27T18:00:00Z",
          quote_observed_at_utc="2026-09-27T18:29:00Z",capture_code_git_sha="c"*40,
          book="draftkings",quote_sha256="1"*64,market="spread",selection="home",
          line=-4.5,price_american=-115,opposite_price_american=-105,raw_prediction=6)
        later_evidence=build_evidence(
          later,artifact=a,closing_quote_at_utc="2026-09-27T19:40:00Z",
          closing_book="draftkings",closing_line=-4.5,closing_price_american=-130,
          closing_opposite_price_american=110,closing_quote_sha256="2"*64,
          settled_at_utc="2026-09-27T23:30:00Z",home_score=27,away_score=20,
          settlement_source_sha256="f"*64)
        out=evaluate_truth_gate(
          [later,early],[later_evidence,early_evidence],artifact=a,
          governance=self.governance(),ci_attested=True,pit_integrity_verified=True,
          truth_gate_floor_verified=True)
        self.assertEqual(out["submitted_decisions"],2)
        self.assertEqual(out["unique_game_market_selection_decisions"],1)
        self.assertEqual(out["suppressed_duplicate_capture_decisions"],1)
        self.assertEqual(out["suppressed_duplicate_capture_evidence_rows"],1)
        self.assertEqual(out["paired_decisions"],1)
        self.assertEqual(out["eligible_decisions"],1)
        self.assertEqual(
          out["decision_uniqueness_policy"],
          "EARLIEST_VALID_DECISION_AT_UTC_THEN_SHA256_PER_GAME_MARKET_SELECTION")

    def test_future_unsettled_decision_reports_pending_with_explicit_asof(self):
        a,d,_=self.pair()
        out=evaluate_truth_gate(
          [d],[],artifact=a,governance=self.governance(),
          ci_attested=True,pit_integrity_verified=True,truth_gate_floor_verified=True,
          evaluation_asof_utc="2026-09-27T19:00:00Z")
        self.assertEqual(out["pending_evidence_decisions"],1)
        self.assertEqual(out["missing_evidence_decisions"],0)
        self.assertEqual(out["evidence_coverage"],0.0)
        self.assertFalse(out["checks"]["complete_evidence_coverage"])
        self.assertEqual(out["status"],"BLOCKED")


if __name__=="__main__":
    unittest.main()
