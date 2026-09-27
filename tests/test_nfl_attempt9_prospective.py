import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.sports.nfl.attempt9_model_p import (
    CALIBRATION_CONTRACT, CANDIDATE_ID, MODEL_P_ID, MODEL_P_SCHEMA,
    MODEL_P_STATUS, canonical_sha256 as artifact_sha,
)
from sportsedge.sports.nfl.attempt9_prospective import build_decision, validate_decision, write_decision_once


class NFLAttempt9ProspectiveTests(unittest.TestCase):
    def artifact(self):
        a={
            "schema_version":MODEL_P_SCHEMA,"status":MODEL_P_STATUS,
            "model_p_id":MODEL_P_ID,"candidate_id":CANDIDATE_ID,
            "code_git_sha":"1"*40,"runtime_artifact_sha256":"a"*64,"source_sha256":"b"*64,
            "calibration_fit":{"contract":CALIBRATION_CONTRACT,"seasons":[2017,2018,2019],
                "role":"SELECTION_EXPOSED_FIT_ONLY_NOT_PROMOTION_EVIDENCE"},
            "markets":{
                "spread":{"sigma":13.8,"calibration_blocks":[{"lo":0.0,"hi":1.0,"weight":500,"mean":0.55}]},
                "total":{"sigma":14.0,"calibration_blocks":[{"lo":0.0,"hi":1.0,"weight":500,"mean":0.52}]},
            },
            "authority":{"creates_model_p":True,"historical_fit_promotion_authority":False,
                "deployed":False,"truth_gate_pass":False,"official_authority":False,"staking_authority":False},
        }
        a["artifact_sha256"]=artifact_sha(a)
        return a

    def kwargs(self):
        return dict(
            artifact=self.artifact(), game_id="2026_03_A_B",
            kickoff_utc="2026-09-27T20:00:00Z",
            decision_at_utc="2026-09-27T18:00:00Z",
            feature_asof_utc="2026-09-27T17:30:00Z",
            quote_observed_at_utc="2026-09-27T17:59:00Z",
            capture_code_git_sha="c"*40, book="draftkings", quote_sha256="d"*64,
            market="spread", selection="home", line=-3.5, price_american=-110,
            raw_prediction=6.0,
        )

    def test_builds_model_p_evidence_without_authority(self):
        row=build_decision(**self.kwargs())
        validate_decision(row)
        self.assertEqual(row["model_p_id"],MODEL_P_ID)
        self.assertIsNone(row["outcome"])
        self.assertIsNone(row["closing_market"])
        self.assertFalse(row["promotion_authority"])
        self.assertFalse(row["official_authority"])

    def test_integer_line_fails_closed(self):
        kw=self.kwargs(); kw["line"]=-3.0
        with self.assertRaisesRegex(ValueError,"PUSH_MODEL_REQUIRED"):
            build_decision(**kw)

    def test_moneyline_fails_closed(self):
        kw=self.kwargs(); kw["market"]="moneyline"
        with self.assertRaisesRegex(ValueError,"MARKET_UNSUPPORTED"):
            build_decision(**kw)

    def test_invalid_price_fails_closed(self):
        kw=self.kwargs(); kw["price_american"]=float("nan")
        with self.assertRaisesRegex(ValueError,"PRICE_INVALID"):
            build_decision(**kw)

    def test_post_kick_decision_fails_closed(self):
        kw=self.kwargs(); kw["decision_at_utc"]="2026-09-27T20:00:00Z"
        with self.assertRaisesRegex(ValueError,"PIT_VIOLATION"):
            build_decision(**kw)

    def test_future_data_mutation_invalidates_record(self):
        row=build_decision(**self.kwargs())
        row["outcome"]={"home_score":30,"away_score":20}
        with self.assertRaisesRegex(ValueError,"FUTURE_DATA_FORBIDDEN"):
            validate_decision(row)

    def test_hash_mutation_is_detected(self):
        row=build_decision(**self.kwargs())
        row["model_p"]=0.99
        with self.assertRaisesRegex(ValueError,"DECISION_SHA_MISMATCH"):
            validate_decision(row)

    def test_artifact_aware_replay_rejects_rehashed_probability_mutation(self):
        row=build_decision(**self.kwargs())
        row["model_p"]=0.99
        from sportsedge.sports.nfl.attempt9_prospective import canonical_sha256
        row["decision_sha256"]=canonical_sha256({k:v for k,v in row.items() if k!="decision_sha256"})
        with self.assertRaisesRegex(ValueError,"MODEL_P_REPLAY_MISMATCH"):
            validate_decision(row, artifact=self.artifact())

    def test_write_once_is_idempotent_and_never_overwrites(self):
        row=build_decision(**self.kwargs())
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision.json"
            self.assertTrue(write_decision_once(path,row,artifact=self.artifact()))
            original=path.read_text(encoding="utf-8")
            self.assertFalse(write_decision_once(path,row,artifact=self.artifact()))
            self.assertEqual(path.read_text(encoding="utf-8"),original)

            changed=dict(row)
            changed["price_american"]=-105.0
            from sportsedge.sports.nfl.attempt9_prospective import canonical_sha256
            changed["decision_sha256"]=canonical_sha256({k:v for k,v in changed.items() if k!="decision_sha256"})
            with self.assertRaisesRegex(ValueError,"IMMUTABLE_CONFLICT"):
                write_decision_once(path,changed,artifact=self.artifact())
            self.assertEqual(path.read_text(encoding="utf-8"),original)

    def test_write_once_rejects_existing_corrupt_file(self):
        row=build_decision(**self.kwargs())
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"decision.json"
            path.write_text("{not-json",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"EXISTING_RECORD_INVALID"):
                write_decision_once(path,row,artifact=self.artifact())


if __name__=="__main__":
    unittest.main()
