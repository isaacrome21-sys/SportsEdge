from __future__ import annotations

from hashlib import sha256
import json
import unittest

from scripts.activate_cfb_selected_candidate_freeze import (
    CFBSelectedFreezeActivationError,
    build_activation,
)
from sportsedge.sports.cfb.candidate_model_v2 import candidate_feature_names
from sportsedge.sports.cfb.candidate_registry_v2 import EQUAL
from sportsedge.sports.cfb.selected_candidate_artifact import build_cfb_selected_candidate_artifact
from sportsedge.sports.cfb.selected_candidate_model import (
    CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT,
    CFB_SELECTED_CANDIDATE_MODEL_ID,
    CFBSelectedCandidateScoreModel,
)


def canonical_sha(value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return sha256(raw).hexdigest()


class CFBSelectedCandidateFreezeActivationTests(unittest.TestCase):
    def fixture(self):
        names=candidate_feature_names(EQUAL)
        model=CFBSelectedCandidateScoreModel(
            model_id=CFB_SELECTED_CANDIDATE_MODEL_ID,
            feature_contract=CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT,
            family=EQUAL,
            feature_names=names,
            feature_means=tuple(0.0 for _ in names),
            feature_scales=tuple(1.0 for _ in names),
            home_coefficients=tuple([24.0]+[0.0 for _ in names]),
            away_coefficients=tuple([21.0]+[0.0 for _ in names]),
            residual_pairs=((1.0,-1.0),(-1.0,1.0)),
            overtime_deltas=((7,0),(0,7)),
            train_seasons=(2015,2025),
            ridge_alpha=10.0,
        )
        authority={
            "model_p":False,"truth_gate":False,"promotion":False,
            "eligibility":False,"staking":False,"evidence_clock":False,
            "official":False,"backfill":False,
        }
        result={
            "schema":"CFB_CANDIDATE_BAKEOFF_RESULT_V2",
            "status":"WINNER_SELECTED_FOR_FREEZE",
            "winner":EQUAL,
            "authority":dict(authority),
        }
        result["result_sha256"]=canonical_sha(result)
        rows_sha="b"*64
        code_sha="a"*64
        proposal=build_cfb_selected_candidate_artifact(
            model,
            model_code_sha256=code_sha,
            training_source_sha256=rows_sha,
            selection_result_sha256=result["result_sha256"],
        )
        proposal_bytes=(json.dumps(proposal,indent=2,sort_keys=True)+"\n").encode()
        source={"responses":[{"query_sha256":"1"*64,"response_sha256":"2"*64}]}
        source_sha=canonical_sha(source)
        bundle={
            "schema":"CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1",
            "status":"READY_FOR_CANDIDATE_EVALUATION",
            "selection_rows_sha256":rows_sha,
            "source_manifest_sha256":source_sha,
            "predictive_code_manifest_sha256":"c"*64,
            "acquisition_code_manifest_sha256":"d"*64,
            "attempt_consumed":False,
            "evaluation_performed":False,
            "historical_pit_created":False,
            "model_p_created":False,
            "truth_gate_authority":False,
            "promotion_authority":False,
            "staking_authority":False,
            "eligibility_changed":False,
            "official_authority":False,
        }
        attestation={
            "schema":"CFB_SELECTED_CANDIDATE_BUILD_ATTESTATION_V1",
            "status":"MODEL_PROPOSAL_BUILT_ZERO_AUTHORITY",
            "candidate_family":EQUAL,
            "model_artifact_sha256":proposal["artifact_sha256"],
            "model_artifact_file_sha256":sha256(proposal_bytes).hexdigest(),
            "selection_result_sha256":result["result_sha256"],
            "selection_rows_sha256":rows_sha,
            "source_manifest_sha256":source_sha,
            "predictive_code_manifest_sha256":"c"*64,
            "acquisition_code_manifest_sha256":"d"*64,
            "model_code_surface_sha256":code_sha,
            "train_seasons":[2015,2025],
            "authority":dict(authority),
        }
        registry={
            "schema_version":1,
            "sport":"CFB",
            "model_family":"CFB_SELECTED_CANDIDATE_MODEL_V1",
            "status":"UNFROZEN",
            "artifact_path":"models/cfb_joint_v1.json",
            "artifact_schema_required":"CFB_SELECTED_CANDIDATE_MODEL_ARTIFACT_V1",
            "runtime_contract_required":"CFB_SELECTED_CANDIDATE_CANONICAL_RUNTIME_V1",
            "artifact_sha256":None,
            "artifact_file_sha256":None,
            "model_code_sha256":None,
            "training_source_sha256":None,
            "source_manifest_sha256":None,
            "predictive_code_manifest_sha256":None,
            "acquisition_code_manifest_sha256":None,
            "fit_max_season":None,
            "promotion_authority":False,
            "evidence_clock_authority":False,
            "blocker":"CFB_RECONSTRUCTED_TRAINING_AND_SELECTION_NOT_COMPLETE",
        }
        return proposal_bytes,proposal,attestation,result,bundle,source,registry,code_sha

    def test_builds_exact_zero_authority_freeze_proposal(self):
        proposal_bytes,proposal,attestation,result,bundle,source,registry,code_sha=self.fixture()
        artifact,frozen=build_activation(
            proposal_bytes=proposal_bytes,
            proposal=proposal,
            build_attestation=attestation,
            bakeoff_result=result,
            selection_bundle=bundle,
            source_manifest=source,
            current_registry=registry,
            current_model_code_sha256=code_sha,
        )
        self.assertEqual(artifact,proposal_bytes)
        self.assertEqual(frozen["status"],"FROZEN")
        self.assertEqual(frozen["selected_candidate_family"],EQUAL)
        self.assertEqual(frozen["artifact_sha256"],proposal["artifact_sha256"])
        self.assertEqual(frozen["artifact_file_sha256"],sha256(proposal_bytes).hexdigest())
        self.assertFalse(frozen["promotion_authority"])
        self.assertFalse(frozen["evidence_clock_authority"])
        self.assertIsNone(frozen["blocker"])

    def test_rejects_code_surface_drift(self):
        args=list(self.fixture())
        with self.assertRaisesRegex(CFBSelectedFreezeActivationError,"CODE_SURFACE_DRIFT"):
            build_activation(
                proposal_bytes=args[0],proposal=args[1],build_attestation=args[2],
                bakeoff_result=args[3],selection_bundle=args[4],source_manifest=args[5],
                current_registry=args[6],current_model_code_sha256="9"*64,
            )


if __name__=="__main__":
    unittest.main()
