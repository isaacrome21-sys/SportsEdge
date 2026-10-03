#!/usr/bin/env python3
"""Build a commit-ready CFB selected-candidate freeze from already-frozen evidence.

This script performs no training, candidate evaluation, retuning, promotion, staking,
evidence-clock start, backfill, or OFFICIAL action. It only verifies the immutable
winner/model proposal evidence and emits exact artifact bytes plus a FROZEN registry
proposal for a separate reviewed main-branch commit.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.selected_candidate_artifact import (
    CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA,
    cfb_selected_candidate_code_surface_sha256,
    load_cfb_selected_candidate_artifact,
)

_HEX64=re.compile(r"^[0-9a-f]{64}$")


class CFBSelectedFreezeActivationError(ValueError):
    pass


def _hex(value: Any, code: str) -> str:
    token=str(value or "").strip().lower()
    if not _HEX64.fullmatch(token):
        raise CFBSelectedFreezeActivationError(code)
    return token


def _canonical_sha(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _zero_authority(value: object, code: str) -> None:
    if not isinstance(value, Mapping) or any(item is not False for item in value.values()):
        raise CFBSelectedFreezeActivationError(code)


def build_activation(
    *,
    proposal_bytes: bytes,
    proposal: Mapping[str, Any],
    build_attestation: Mapping[str, Any],
    bakeoff_result: Mapping[str, Any],
    selection_bundle: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    current_registry: Mapping[str, Any],
    current_model_code_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    if proposal.get("schema_version") != CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_ARTIFACT_SCHEMA_INVALID")
    _zero_authority(proposal.get("authority"), "CFB_SELECTED_FREEZE_ARTIFACT_AUTHORITY_LEAK")
    artifact_sha=_hex(proposal.get("artifact_sha256"),"CFB_SELECTED_FREEZE_ARTIFACT_SHA_INVALID")
    file_sha=sha256(proposal_bytes).hexdigest()

    if build_attestation.get("schema") != "CFB_SELECTED_CANDIDATE_BUILD_ATTESTATION_V1":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_ATTESTATION_SCHEMA_INVALID")
    if build_attestation.get("status") != "MODEL_PROPOSAL_BUILT_ZERO_AUTHORITY":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_ATTESTATION_STATUS_INVALID")
    _zero_authority(build_attestation.get("authority"), "CFB_SELECTED_FREEZE_BUILD_AUTHORITY_LEAK")
    if _hex(build_attestation.get("model_artifact_sha256"),"CFB_SELECTED_FREEZE_BUILD_ARTIFACT_SHA_INVALID") != artifact_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_ARTIFACT_SHA_MISMATCH")
    if _hex(build_attestation.get("model_artifact_file_sha256"),"CFB_SELECTED_FREEZE_BUILD_FILE_SHA_INVALID") != file_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_FILE_SHA_MISMATCH")

    if bakeoff_result.get("schema") != "CFB_CANDIDATE_BAKEOFF_RESULT_V2":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BAKEOFF_SCHEMA_INVALID")
    if bakeoff_result.get("status") != "WINNER_SELECTED_FOR_FREEZE":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BAKEOFF_WINNER_REQUIRED")
    _zero_authority(bakeoff_result.get("authority"), "CFB_SELECTED_FREEZE_BAKEOFF_AUTHORITY_LEAK")
    claimed_result=_hex(bakeoff_result.get("result_sha256"),"CFB_SELECTED_FREEZE_RESULT_SHA_INVALID")
    unhashed=dict(bakeoff_result); unhashed.pop("result_sha256",None)
    if _canonical_sha(unhashed) != claimed_result:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_RESULT_SHA_MISMATCH")
    if _hex(proposal.get("selection_result_sha256"),"CFB_SELECTED_FREEZE_PROPOSAL_RESULT_SHA_INVALID") != claimed_result:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_PROPOSAL_RESULT_BINDING_MISMATCH")
    if _hex(build_attestation.get("selection_result_sha256"),"CFB_SELECTED_FREEZE_BUILD_RESULT_SHA_INVALID") != claimed_result:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_RESULT_BINDING_MISMATCH")
    winner=str(bakeoff_result.get("winner") or "")
    if not winner or str(proposal.get("candidate_family") or "") != winner or str(build_attestation.get("candidate_family") or "") != winner:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_WINNER_BINDING_MISMATCH")

    if selection_bundle.get("schema") != "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1" or selection_bundle.get("status") != "READY_FOR_CANDIDATE_EVALUATION":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_SELECTION_BUNDLE_INVALID")
    for key in ("attempt_consumed","evaluation_performed","historical_pit_created","model_p_created","truth_gate_authority","promotion_authority","staking_authority","eligibility_changed","official_authority"):
        if selection_bundle.get(key) is not False:
            raise CFBSelectedFreezeActivationError(f"CFB_SELECTED_FREEZE_SELECTION_BUNDLE_AUTHORITY_INVALID:{key}")

    rows_sha=_hex(selection_bundle.get("selection_rows_sha256"),"CFB_SELECTED_FREEZE_ROWS_SHA_INVALID")
    source_sha=_hex(selection_bundle.get("source_manifest_sha256"),"CFB_SELECTED_FREEZE_SOURCE_MANIFEST_SHA_INVALID")
    predictive_sha=_hex(selection_bundle.get("predictive_code_manifest_sha256"),"CFB_SELECTED_FREEZE_PREDICTIVE_SHA_INVALID")
    acquisition_sha=_hex(selection_bundle.get("acquisition_code_manifest_sha256"),"CFB_SELECTED_FREEZE_ACQUISITION_SHA_INVALID")
    if _canonical_sha(source_manifest) != source_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_SOURCE_MANIFEST_CONTENT_MISMATCH")
    if _hex(proposal.get("training_source_sha256"),"CFB_SELECTED_FREEZE_TRAINING_SHA_INVALID") != rows_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_TRAINING_BINDING_MISMATCH")
    for key,expected in (
        ("selection_rows_sha256",rows_sha),
        ("source_manifest_sha256",source_sha),
        ("predictive_code_manifest_sha256",predictive_sha),
        ("acquisition_code_manifest_sha256",acquisition_sha),
    ):
        if _hex(build_attestation.get(key),f"CFB_SELECTED_FREEZE_BUILD_BINDING_INVALID:{key}") != expected:
            raise CFBSelectedFreezeActivationError(f"CFB_SELECTED_FREEZE_BUILD_BINDING_MISMATCH:{key}")

    code_sha=_hex(current_model_code_sha256,"CFB_SELECTED_FREEZE_CURRENT_CODE_SHA_INVALID")
    if _hex(proposal.get("model_code_sha256"),"CFB_SELECTED_FREEZE_PROPOSAL_CODE_SHA_INVALID") != code_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_CODE_SURFACE_DRIFT")
    if _hex(build_attestation.get("model_code_surface_sha256"),"CFB_SELECTED_FREEZE_BUILD_CODE_SHA_INVALID") != code_sha:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_BUILD_CODE_BINDING_MISMATCH")
    load_cfb_selected_candidate_artifact(
        proposal,
        expected_model_code_sha256=code_sha,
        expected_training_source_sha256=rows_sha,
        expected_selection_result_sha256=claimed_result,
    )

    if current_registry.get("schema_version") != 1 or current_registry.get("sport") != "CFB" or current_registry.get("status") != "UNFROZEN":
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_REGISTRY_NOT_UNFROZEN")
    if current_registry.get("promotion_authority") is not False or current_registry.get("evidence_clock_authority") is not False:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_REGISTRY_AUTHORITY_INVALID")
    seasons=build_attestation.get("train_seasons")
    if not isinstance(seasons,list) or not seasons:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_TRAIN_SEASONS_MISSING")
    fit_max=max(int(x) for x in seasons)
    if fit_max != 2025:
        raise CFBSelectedFreezeActivationError("CFB_SELECTED_FREEZE_FIT_MAX_SEASON_INVALID")

    registry=dict(current_registry)
    registry.update({
        "model_family":"CFB_SELECTED_CANDIDATE_MODEL_V1",
        "status":"FROZEN",
        "artifact_path":"models/cfb_joint_v1.json",
        "artifact_schema_required":"CFB_SELECTED_CANDIDATE_MODEL_ARTIFACT_V1",
        "runtime_contract_required":"CFB_SELECTED_CANDIDATE_CANONICAL_RUNTIME_V1",
        "selected_candidate_family":winner,
        "selection_result_sha256":claimed_result,
        "artifact_sha256":artifact_sha,
        "artifact_file_sha256":file_sha,
        "model_code_sha256":code_sha,
        "training_source_sha256":rows_sha,
        "source_manifest_sha256":source_sha,
        "predictive_code_manifest_sha256":predictive_sha,
        "acquisition_code_manifest_sha256":acquisition_sha,
        "fit_max_season":fit_max,
        "promotion_authority":False,
        "evidence_clock_authority":False,
        "blocker":None,
    })
    return proposal_bytes, registry


def _load(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    raw=path.read_bytes()
    value=json.loads(raw.decode("utf-8"))
    if not isinstance(value,Mapping):
        raise CFBSelectedFreezeActivationError(f"CFB_SELECTED_FREEZE_JSON_OBJECT_REQUIRED:{path}")
    return raw,value


def main(argv: list[str] | None=None) -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--model-proposal",type=Path,required=True)
    ap.add_argument("--build-attestation",type=Path,required=True)
    ap.add_argument("--bakeoff-result",type=Path,required=True)
    ap.add_argument("--selection-bundle",type=Path,required=True)
    ap.add_argument("--source-manifest",type=Path,required=True)
    ap.add_argument("--registry",type=Path,default=ROOT/"config/cfb_game_model_freeze.json")
    ap.add_argument("--artifact-out",type=Path,default=ROOT/"models/cfb_joint_v1.json")
    ap.add_argument("--registry-out",type=Path,default=ROOT/"artifacts/cfb/cfb_game_model_freeze_proposal.json")
    args=ap.parse_args(argv)

    proposal_bytes,proposal=_load(args.model_proposal)
    _,attestation=_load(args.build_attestation)
    _,result=_load(args.bakeoff_result)
    _,bundle=_load(args.selection_bundle)
    _,source=_load(args.source_manifest)
    _,registry=_load(args.registry)
    artifact_bytes,frozen=build_activation(
        proposal_bytes=proposal_bytes,
        proposal=proposal,
        build_attestation=attestation,
        bakeoff_result=result,
        selection_bundle=bundle,
        source_manifest=source,
        current_registry=registry,
        current_model_code_sha256=cfb_selected_candidate_code_surface_sha256(ROOT),
    )
    args.artifact_out.parent.mkdir(parents=True,exist_ok=True)
    args.registry_out.parent.mkdir(parents=True,exist_ok=True)
    args.artifact_out.write_bytes(artifact_bytes)
    args.registry_out.write_text(json.dumps(frozen,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":"FREEZE_COMMIT_PROPOSAL_BUILT",
        "candidate_family":frozen["selected_candidate_family"],
        "artifact_sha256":frozen["artifact_sha256"],
        "artifact_file_sha256":frozen["artifact_file_sha256"],
        "promotion_authority":False,
        "evidence_clock_authority":False,
        "official_authority":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
