"""Final NFL deployment bridge requiring independent CI and forward-CLV authenticity."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.core.validation.nfl_forward_clv_attestation import canonical_clv_payload_sha256
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT=re.compile(r"^[0-9a-f]{40}$"); _SHA=re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_WORKFLOW="football-nfl-forward-clv-collection"
_EXPECTED_CONTRACT="NFL_FORWARD_CLV_COLLECTION_V2"
_EXPECTED_PROMOTION_DECISIONS="SHADOW_QUALIFIED_OR_OFFICIAL"


def _map(v:Any,e:str)->Mapping[str,Any]:
    if not isinstance(v,Mapping): raise ValueError(e)
    return v

def _hash(v:Any,e:str)->str:
    x=str(v or "").strip().lower()
    if not _SHA.fullmatch(x): raise ValueError(e)
    return x

def _git(v:Any,e:str)->str:
    x=str(v or "").strip().lower()
    if not _GIT.fullmatch(x): raise ValueError(e)
    return x

def _count(v:Any,e:str)->int:
    if isinstance(v,bool) or not isinstance(v,int) or v<0: raise ValueError(e)
    return v


def verify_nfl_forward_clv_attestation(clv_evidence:Mapping[str,Any], clv_attestation:Mapping[str,Any]|None, *, expected_code_sha:str, ci_attestation:Mapping[str,Any]|None=None)->dict[str,Any]:
    a=_map(clv_attestation,"NFL_FORWARD_CLV_ATTESTATION_REQUIRED")
    if int(a.get("schema_version",0))!=2: raise ValueError("NFL_FORWARD_CLV_ATTESTATION_SCHEMA_INVALID")
    if a.get("collector_contract")!=_EXPECTED_CONTRACT: raise ValueError("NFL_FORWARD_CLV_COLLECTOR_CONTRACT_INVALID")
    if a.get("workflow_name")!=_EXPECTED_WORKFLOW: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NAME_MISMATCH")
    if str(a.get("workflow_conclusion") or "").lower()!="success": raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NOT_SUCCESSFUL")
    if str(a.get("workflow_event") or "").lower()!="schedule": raise ValueError("NFL_FORWARD_CLV_WORKFLOW_EVENT_INVALID")
    if str(a.get("workflow_head_branch") or "")!="main": raise ValueError("NFL_FORWARD_CLV_HEAD_BRANCH_INVALID")
    try: run_id=int(a.get("workflow_run_id"))
    except (TypeError,ValueError) as exc: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID") from exc
    if run_id<=0: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID")

    code=_git(a.get("git_sha"),"NFL_FORWARD_CLV_CODE_SHA_INVALID")
    if code!=_git(expected_code_sha,"NFL_FORWARD_CLV_EXPECTED_CODE_SHA_INVALID"): raise ValueError("NFL_FORWARD_CLV_CODE_SHA_MISMATCH")
    if clv_evidence.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or a.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID: raise ValueError("NFL_FORWARD_CLV_MODEL_ID_MISMATCH")
    if clv_evidence.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT or a.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise ValueError("NFL_FORWARD_CLV_FEATURE_CONTRACT_MISMATCH")
    if clv_evidence.get("promotion_decision_contract")!=_EXPECTED_PROMOTION_DECISIONS: raise ValueError("NFL_FORWARD_CLV_PROMOTION_DECISION_CONTRACT_INVALID")

    model_hash=_hash(clv_evidence.get("model_artifact_sha256"),"NFL_FORWARD_CLV_MODEL_ARTIFACT_SHA256_INVALID")
    if _hash(a.get("model_artifact_sha256"),"NFL_FORWARD_CLV_ATTESTED_MODEL_ARTIFACT_SHA256_INVALID")!=model_hash: raise ValueError("NFL_FORWARD_CLV_MODEL_ARTIFACT_MISMATCH")
    if ci_attestation is not None:
        ci=_map(ci_attestation,"NFL_CI_ATTESTATION_EVIDENCE_REQUIRED")
        if _git(ci.get("git_sha"),"NFL_FORWARD_CLV_CI_CODE_SHA_INVALID")!=code: raise ValueError("NFL_FORWARD_CLV_CI_CODE_SHA_MISMATCH")
        if _hash(ci.get("model_artifact_sha256"),"NFL_FORWARD_CLV_CI_MODEL_ARTIFACT_SHA_INVALID")!=model_hash: raise ValueError("NFL_FORWARD_CLV_CI_MODEL_ARTIFACT_MISMATCH")

    dh=_hash(clv_evidence.get("decision_log_sha256"),"NFL_FORWARD_CLV_DECISION_LOG_SHA256_INVALID")
    ch=_hash(clv_evidence.get("close_log_sha256"),"NFL_FORWARD_CLV_CLOSE_LOG_SHA256_INVALID")
    if _hash(a.get("decision_log_sha256"),"NFL_FORWARD_CLV_ATTESTED_DECISION_LOG_SHA256_INVALID")!=dh: raise ValueError("NFL_FORWARD_CLV_DECISION_LOG_MISMATCH")
    if _hash(a.get("close_log_sha256"),"NFL_FORWARD_CLV_ATTESTED_CLOSE_LOG_SHA256_INVALID")!=ch: raise ValueError("NFL_FORWARD_CLV_CLOSE_LOG_MISMATCH")
    payload=canonical_clv_payload_sha256(clv_evidence)
    if _hash(a.get("clv_payload_sha256"),"NFL_FORWARD_CLV_PAYLOAD_SHA256_INVALID")!=payload: raise ValueError("NFL_FORWARD_CLV_PAYLOAD_MISMATCH")
    dc=_count(clv_evidence.get("decision_count"),"NFL_FORWARD_CLV_DECISION_COUNT_INVALID"); cc=_count(clv_evidence.get("close_count"),"NFL_FORWARD_CLV_CLOSE_COUNT_INVALID"); uc=_count(clv_evidence.get("unique_observation_count"),"NFL_FORWARD_CLV_UNIQUE_COUNT_INVALID")
    if _count(a.get("decision_count"),"NFL_FORWARD_CLV_ATTESTED_DECISION_COUNT_INVALID")!=dc: raise ValueError("NFL_FORWARD_CLV_DECISION_COUNT_MISMATCH")
    if _count(a.get("close_count"),"NFL_FORWARD_CLV_ATTESTED_CLOSE_COUNT_INVALID")!=cc: raise ValueError("NFL_FORWARD_CLV_CLOSE_COUNT_MISMATCH")
    if _count(a.get("unique_observation_count"),"NFL_FORWARD_CLV_ATTESTED_UNIQUE_COUNT_INVALID")!=uc: raise ValueError("NFL_FORWARD_CLV_UNIQUE_COUNT_MISMATCH")
    try: verified=int(a.get("verified_artifact_count"))
    except (TypeError,ValueError) as exc: raise ValueError("NFL_FORWARD_CLV_VERIFIED_ARTIFACT_COUNT_INVALID") from exc
    if verified<4: raise ValueError("NFL_FORWARD_CLV_VERIFIED_ARTIFACT_COUNT_INVALID")
    return {"schema_version":2,"collector_contract":_EXPECTED_CONTRACT,"workflow_name":_EXPECTED_WORKFLOW,"workflow_conclusion":"success","workflow_event":"schedule","workflow_head_branch":"main","workflow_run_id":run_id,"collector_git_sha":_git(a.get("collector_git_sha"),"NFL_FORWARD_CLV_COLLECTOR_CODE_SHA_INVALID"),"git_sha":code,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"model_artifact_sha256":model_hash,"decision_log_sha256":dh,"close_log_sha256":ch,"clv_payload_sha256":payload,"decision_count":dc,"close_count":cc,"unique_observation_count":uc,"verified_artifact_count":verified}


def build_externally_attested_nfl_registry(math_artifact:Mapping[str,Any], historical_evidence:Mapping[str,Any], *, declared_markets:Iterable[str], ci_attestation:Mapping[str,Any], clv_evidence:Mapping[str,Any], clv_attestation:Mapping[str,Any]|None)->dict[str,Any]:
    expected=str(math_artifact.get("code_git_sha") or "").strip().lower()
    verified=verify_nfl_forward_clv_attestation(clv_evidence,clv_attestation,expected_code_sha=expected,ci_attestation=ci_attestation)
    registry=build_nfl_promotion_registry(math_artifact,historical_evidence,declared_markets=declared_markets,ci_attested=True,ci_attestation=ci_attestation,clv_evidence=clv_evidence)
    registry["clv_attestation_state"]="EXTERNALLY_ATTESTED"; registry["clv_attestation"]=verified
    return registry
