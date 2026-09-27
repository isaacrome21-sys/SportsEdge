import tempfile
import unittest
from pathlib import Path

from sportsedge.sports.nfl.attempt9_model_p import (
    CALIBRATION_CONTRACT, CANDIDATE_ID, MODEL_P_ID, MODEL_P_SCHEMA,
    MODEL_P_STATUS, canonical_sha256 as artifact_sha,
)
from sportsedge.sports.nfl.attempt9_prospective import build_decision
from sportsedge.sports.nfl.attempt9_prospective_evidence import (
    build_evidence, validate_evidence, write_evidence_once,
)


class NFLAttempt9ProspectiveEvidenceTests(unittest.TestCase):
    def artifact(self):
        a={"schema_version":MODEL_P_SCHEMA,"status":MODEL_P_STATUS,"model_p_id":MODEL_P_ID,
           "candidate_id":CANDIDATE_ID,"code_git_sha":"1"*40,"runtime_artifact_sha256":"a"*64,
           "source_sha256":"b"*64,
           "calibration_fit":{"contract":CALIBRATION_CONTRACT,"seasons":[2017,2018,2019],
             "role":"SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE"},
           "markets":{"spread":{"sigma":13.8,"calibration_blocks":[{"lo":0.0,"hi":1.0,"weight":500,"mean":0.55}]},
                      "total":{"sigma":14.0,"calibration_blocks":[{"lo":0.0,"hi":1.0,"weight":500,"mean":0.52}]}},
           "authority":{"creates_model_p":True,"historical_fit_promotion_authority":False,
             "deployed":False,"truth_gate_pass":False,"official_authority":False,"staking_authority":False}}
        a["artifact_sha256"]=artifact_sha(a); return a

    def decision(self):
        return build_decision(artifact=self.artifact(),game_id="2026_03_A_B",
          kickoff_utc="2026-09-27T20:00:00Z",decision_at_utc="2026-09-27T18:00:00Z",
          feature_asof_utc="2026-09-27T17:30:00Z",quote_observed_at_utc="2026-09-27T17:59:00Z",
          capture_code_git_sha="c"*40,book="draftkings",quote_sha256="d"*64,
          market="spread",selection="home",line=-3.5,price_american=-110,
          opposite_price_american=-110,raw_prediction=6.0)

    def kwargs(self):
        return dict(artifact=self.artifact(),closing_quote_at_utc="2026-09-27T19:40:00Z",
          closing_book="draftkings",closing_line=-3.5,closing_price_american=-120,
          closing_opposite_price_american=100,closing_quote_sha256="e"*64,
          settled_at_utc="2026-09-27T23:30:00Z",home_score=27,away_score=20,
          settlement_source_sha256="f"*64)

    def test_binds_outcome_and_novig_to_novig_clv_without_authority(self):
        d=self.decision(); row=build_evidence(d,**self.kwargs())
        validate_evidence(row,d,artifact=self.artifact())
        self.assertEqual("WIN",row["outcome"])
        self.assertAlmostEqual(0.5,row["decision_novig_probability"])
        self.assertAlmostEqual((120/220)/((120/220)+.5),row["closing_novig_probability"])
        self.assertAlmostEqual(row["closing_novig_probability"]-.5,row["clv"])
        self.assertFalse(row["promotion_authority"]); self.assertFalse(row["truth_gate_pass"])

    def test_wrong_book_fails_closed(self):
        kw=self.kwargs(); kw["closing_book"]="otherbook"
        with self.assertRaisesRegex(ValueError,"BOOK_MISMATCH"):
            build_evidence(self.decision(),**kw)

    def test_later_different_threshold_is_not_substituted(self):
        kw=self.kwargs(); kw["closing_line"]=-4.5
        with self.assertRaisesRegex(ValueError,"ORIGINAL_THRESHOLD_MISSING"):
            build_evidence(self.decision(),**kw)

    def test_close_outside_final_window_fails_closed(self):
        kw=self.kwargs(); kw["closing_quote_at_utc"]="2026-09-27T19:44:00Z"
        with self.assertRaisesRegex(ValueError,"CLOSE_OUTSIDE_GOVERNED_WINDOW"):
            build_evidence(self.decision(),**kw)

    def test_settlement_must_be_postgame(self):
        kw=self.kwargs(); kw["settled_at_utc"]="2026-09-27T19:59:00Z"
        with self.assertRaisesRegex(ValueError,"SETTLEMENT_NOT_POSTGAME"):
            build_evidence(self.decision(),**kw)

    def test_write_once_never_replaces_evidence(self):
        d=self.decision(); row=build_evidence(d,**self.kwargs())
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"evidence.json"
            self.assertTrue(write_evidence_once(p,row,d,artifact=self.artifact()))
            self.assertFalse(write_evidence_once(p,row,d,artifact=self.artifact()))
            changed=dict(row); changed["home_score"]=30
            with self.assertRaisesRegex(ValueError,"REPLAY_MISMATCH"):
                write_evidence_once(p,changed,d,artifact=self.artifact())


if __name__=="__main__":
    unittest.main()
