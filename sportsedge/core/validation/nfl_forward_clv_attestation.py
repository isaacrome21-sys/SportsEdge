"""External authenticity attestation for scheduled NFL forward-CLV bundles.

Schema v2 separates the scheduled collector's Git head from the pinned NFL model
release SHA. Unrelated repository commits therefore do not erase a season of
forward evidence, while every observation still binds to one exact fitted model
artifact and exact model-code SHA. Schema v1 remains readable for old unit
fixtures but is not accepted by the deployment bridge.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_EXPECTED_WORKFLOW = "football-nfl-forward-clv-collection"
_EXPECTED_EVENT = "schedule"
_EXPECTED_BRANCH = "main"
_CONTRACT_V1 = "NFL_FORWARD_CLV_COLLECTION_V1"
_CONTRACT_V2 = "NFL_FORWARD_CLV_COLLECTION_V2"
_GIT = re.compile(r"^[0-9a-f]{40}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def canonical_clv_payload_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_JSON_INVALID:{path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_NOT_OBJECT:{path.name}")
    return value


def _sha_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_MISSING:{path.name}") from exc


def _git(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT.fullmatch(raw): raise ValueError(error)
    return raw


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA.fullmatch(raw): raise ValueError(error)
    return raw


def _count(value: Any, error: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ValueError(error)
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows=[]
    try: lines=path.read_text(encoding="utf-8").splitlines()
    except OSError as exc: raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_MISSING:{path.name}") from exc
    for i,line in enumerate(lines,1):
        if not line.strip(): continue
        try: row=json.loads(line)
        except json.JSONDecodeError as exc: raise ValueError(f"NFL_FORWARD_CLV_JSONL_INVALID:{path.name}:{i}") from exc
        if not isinstance(row,dict): raise ValueError(f"NFL_FORWARD_CLV_JSONL_ROW_INVALID:{path.name}:{i}")
        rows.append(row)
    if not rows: raise ValueError(f"NFL_FORWARD_CLV_JSONL_EMPTY:{path.name}")
    return rows


def _verify_workflow(name: str, conclusion: str, event: str, branch: str, run_id: int) -> int:
    if str(name)!=_EXPECTED_WORKFLOW: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NAME_MISMATCH")
    if str(conclusion).strip().lower()!="success": raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NOT_SUCCESSFUL")
    if str(event).strip().lower()!=_EXPECTED_EVENT: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_EVENT_INVALID")
    if str(branch).strip()!=_EXPECTED_BRANCH: raise ValueError("NFL_FORWARD_CLV_HEAD_BRANCH_INVALID")
    try: rid=int(run_id)
    except (TypeError,ValueError) as exc: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID") from exc
    if rid<=0: raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID")
    return rid


def _manifest_artifacts(root: Path, manifest: Mapping[str,Any]) -> dict[str,str]:
    raw=manifest.get("artifacts")
    if not isinstance(raw,list) or not raw: raise ValueError("NFL_FORWARD_CLV_ARTIFACT_MANIFEST_EMPTY")
    seen={}
    for row in raw:
        if not isinstance(row,dict): raise ValueError("NFL_FORWARD_CLV_ARTIFACT_MANIFEST_ROW_INVALID")
        name=str(row.get("path") or "").strip()
        if not name or Path(name).name!=name or name in seen: raise ValueError("NFL_FORWARD_CLV_ARTIFACT_PATH_INVALID")
        expected=_hash(row.get("sha256"),f"NFL_FORWARD_CLV_ARTIFACT_SHA256_INVALID:{name}")
        actual=_sha_file(root/name)
        if actual!=expected: raise ValueError(f"NFL_FORWARD_CLV_ARTIFACT_HASH_MISMATCH:{name}")
        seen[name]=actual
    return seen


def _verify_rows(decisions: list[dict[str,Any]], closes: list[dict[str,Any]], *, model_sha: str, model_artifact_sha: str|None) -> None:
    dkeys=set(); obs=set()
    for i,row in enumerate(decisions,1):
        if str(row.get("sport") or "").lower()!="nfl": raise ValueError(f"NFL_FORWARD_CLV_ROW_SPORT_MISMATCH:decision:{i}")
        if row.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or row.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise ValueError(f"NFL_FORWARD_CLV_ROW_MODEL_IDENTITY_MISMATCH:decision:{i}")
        if _git(row.get("code_git_sha"),f"NFL_FORWARD_CLV_ROW_CODE_SHA_INVALID:decision:{i}")!=model_sha: raise ValueError("NFL_FORWARD_CLV_ROW_CODE_SHA_MISMATCH")
        if model_artifact_sha is not None and _hash(row.get("model_artifact_sha256"),f"NFL_FORWARD_CLV_ROW_MODEL_ARTIFACT_SHA_INVALID:{i}")!=model_artifact_sha: raise ValueError("NFL_FORWARD_CLV_ROW_MODEL_ARTIFACT_MISMATCH")
        key=(str(row.get("game_id") or ""),str(row.get("market") or "").lower(),str(row.get("side") or ""),str(row.get("book") or "").lower())
        if not all(key): raise ValueError("NFL_FORWARD_CLV_PAIR_IDENTITY_MISSING")
        if key in dkeys: raise ValueError("NFL_FORWARD_CLV_DUPLICATE_DECISION")
        if key[:3] in obs: raise ValueError("NFL_FORWARD_CLV_DUPLICATE_OBSERVATION")
        dkeys.add(key);obs.add(key[:3])
    ckeys=set()
    for i,row in enumerate(closes,1):
        if str(row.get("sport") or "").lower()!="nfl": raise ValueError(f"NFL_FORWARD_CLV_ROW_SPORT_MISMATCH:close:{i}")
        if row.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or row.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise ValueError(f"NFL_FORWARD_CLV_ROW_MODEL_IDENTITY_MISMATCH:close:{i}")
        if _git(row.get("code_git_sha"),f"NFL_FORWARD_CLV_ROW_CODE_SHA_INVALID:close:{i}")!=model_sha: raise ValueError("NFL_FORWARD_CLV_ROW_CODE_SHA_MISMATCH")
        key=(str(row.get("game_id") or ""),str(row.get("market") or "").lower(),str(row.get("side") or ""),str(row.get("book") or "").lower())
        if not all(key): raise ValueError("NFL_FORWARD_CLV_PAIR_IDENTITY_MISSING")
        if key in ckeys: raise ValueError("NFL_FORWARD_CLV_DUPLICATE_CLOSE")
        ckeys.add(key)
    if dkeys!=ckeys: raise ValueError("NFL_FORWARD_CLV_DECISION_CLOSE_IDENTITY_MISMATCH")


def verify_nfl_forward_clv_bundle(bundle_dir: Path|str, *, workflow_name: str, workflow_conclusion: str, workflow_event: str, workflow_head_branch: str, workflow_head_sha: str, workflow_run_id: int) -> dict[str,Any]:
    run_id=_verify_workflow(workflow_name,workflow_conclusion,workflow_event,workflow_head_branch,workflow_run_id)
    workflow_sha=_git(workflow_head_sha,"NFL_FORWARD_CLV_WORKFLOW_HEAD_SHA_INVALID")
    root=Path(bundle_dir); manifest=_json(root/"nfl_forward_clv_manifest.json")
    schema=int(manifest.get("schema_version",0))
    contract=str(manifest.get("collector_contract") or "")
    if schema==1 and contract==_CONTRACT_V1:
        model_sha=_git(manifest.get("git_sha"),"NFL_FORWARD_CLV_MANIFEST_GIT_SHA_INVALID")
        if model_sha!=workflow_sha: raise ValueError("NFL_FORWARD_CLV_HEAD_SHA_MISMATCH")
        collector_sha=workflow_sha; model_artifact_sha=None
        required={"nfl_forward_decisions.jsonl","nfl_forward_closes.jsonl","nfl_clv_evidence.json"}
    elif schema==2 and contract==_CONTRACT_V2:
        collector_sha=_git(manifest.get("collector_git_sha"),"NFL_FORWARD_CLV_COLLECTOR_GIT_SHA_INVALID")
        if collector_sha!=workflow_sha: raise ValueError("NFL_FORWARD_CLV_COLLECTOR_HEAD_SHA_MISMATCH")
        model_sha=_git(manifest.get("model_code_git_sha"),"NFL_FORWARD_CLV_MODEL_CODE_SHA_INVALID")
        model_artifact_sha=_hash(manifest.get("model_artifact_sha256"),"NFL_FORWARD_CLV_MODEL_ARTIFACT_SHA256_INVALID")
        required={"nfl_forward_decisions.jsonl","nfl_forward_closes.jsonl","nfl_clv_evidence.json","nfl_m2_model.json"}
    else:
        raise ValueError("NFL_FORWARD_CLV_MANIFEST_SCHEMA_INVALID")
    if manifest.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or manifest.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise ValueError("NFL_FORWARD_CLV_MANIFEST_MODEL_IDENTITY_MISMATCH")
    seen=_manifest_artifacts(root,manifest)
    if not required.issubset(seen): raise ValueError(f"NFL_FORWARD_CLV_REQUIRED_ARTIFACT_MISSING:{sorted(required-set(seen))[0]}")
    if model_artifact_sha is not None and seen["nfl_m2_model.json"]!=model_artifact_sha: raise ValueError("NFL_FORWARD_CLV_MODEL_ARTIFACT_HASH_MISMATCH")

    decisions=_jsonl(root/"nfl_forward_decisions.jsonl"); closes=_jsonl(root/"nfl_forward_closes.jsonl")
    _verify_rows(decisions,closes,model_sha=model_sha,model_artifact_sha=model_artifact_sha)
    evidence=_json(root/"nfl_clv_evidence.json")
    if int(evidence.get("schema_version",0))!=4 or str(evidence.get("sport") or "").lower()!="nfl": raise ValueError("NFL_FORWARD_CLV_EVIDENCE_SCHEMA_INVALID")
    if evidence.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or evidence.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise ValueError("NFL_FORWARD_CLV_EVIDENCE_MODEL_IDENTITY_MISMATCH")
    if _git(evidence.get("code_git_sha"),"NFL_FORWARD_CLV_EVIDENCE_CODE_SHA_INVALID")!=model_sha: raise ValueError("NFL_FORWARD_CLV_EVIDENCE_CODE_SHA_MISMATCH")
    if model_artifact_sha is not None and _hash(evidence.get("model_artifact_sha256"),"NFL_FORWARD_CLV_EVIDENCE_MODEL_ARTIFACT_SHA_INVALID")!=model_artifact_sha: raise ValueError("NFL_FORWARD_CLV_EVIDENCE_MODEL_ARTIFACT_MISMATCH")
    if _hash(evidence.get("decision_log_sha256"),"NFL_FORWARD_CLV_DECISION_LOG_SHA_INVALID")!=seen["nfl_forward_decisions.jsonl"]: raise ValueError("NFL_FORWARD_CLV_DECISION_LOG_IDENTITY_MISMATCH")
    if _hash(evidence.get("close_log_sha256"),"NFL_FORWARD_CLV_CLOSE_LOG_SHA_INVALID")!=seen["nfl_forward_closes.jsonl"]: raise ValueError("NFL_FORWARD_CLV_CLOSE_LOG_IDENTITY_MISMATCH")
    dc=_count(evidence.get("decision_count"),"NFL_FORWARD_CLV_DECISION_COUNT_INVALID"); cc=_count(evidence.get("close_count"),"NFL_FORWARD_CLV_CLOSE_COUNT_INVALID"); uc=_count(evidence.get("unique_observation_count"),"NFL_FORWARD_CLV_UNIQUE_COUNT_INVALID")
    if (dc,cc,uc)!=(len(decisions),len(closes),len(decisions)): raise ValueError("NFL_FORWARD_CLV_COUNT_MISMATCH")
    return {"schema_version":2 if schema==2 else 1,"collector_contract":contract,"workflow_name":_EXPECTED_WORKFLOW,"workflow_conclusion":"success","workflow_event":_EXPECTED_EVENT,"workflow_head_branch":_EXPECTED_BRANCH,"workflow_run_id":run_id,"collector_git_sha":collector_sha,"git_sha":model_sha,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"model_artifact_sha256":model_artifact_sha,"decision_log_sha256":seen["nfl_forward_decisions.jsonl"],"close_log_sha256":seen["nfl_forward_closes.jsonl"],"clv_payload_sha256":canonical_clv_payload_sha256(evidence),"decision_count":dc,"close_count":cc,"unique_observation_count":uc,"verified_artifact_count":len(seen)}
