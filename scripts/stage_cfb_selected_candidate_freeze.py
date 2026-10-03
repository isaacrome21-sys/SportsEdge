#!/usr/bin/env python3
"""Stage a zero-authority selected CFB model for a separate main-branch freeze PR.

This does not select a model, fit a model, consume an attempt, promote a market,
start an evidence clock, or merge anything. It verifies the already-governed
winner proposal and public reconstruction manifests, then writes the exact
canonical artifact, freeze registry, and freeze-evidence document for review.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.reconstructed_selection import canonical_sha256
from sportsedge.sports.cfb.selected_candidate_artifact import (
    CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA,
    cfb_selected_candidate_code_surface_sha256,
    load_cfb_selected_candidate_artifact,
)


class CFBSelectedFreezeStageError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CFBSelectedFreezeStageError(f"CFB_SELECTED_FREEZE_INPUT_UNREADABLE:{path}") from exc


def _hex64(value: object, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBSelectedFreezeStageError(f"CFB_SELECTED_FREEZE_HASH_INVALID:{name}")
    return text


def _zero_authority(value: object, name: str) -> None:
    if not isinstance(value, Mapping) or any(item is not False for item in value.values()):
        raise CFBSelectedFreezeStageError(f"CFB_SELECTED_FREEZE_AUTHORITY_LEAK:{name}")


def stage(
    *,
    proposal_path: Path,
    attestation_path: Path,
    selection_bundle_path: Path,
    source_manifest_path: Path,
    acquisition_manifest_path: Path,
    bakeoff_result_path: Path,
    artifact_output: Path,
    registry_output: Path,
    evidence_output: Path,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    proposal = _load(proposal_path)
    attestation = _load(attestation_path)
    bundle = _load(selection_bundle_path)
    source_manifest = _load(source_manifest_path)
    acquisition = _load(acquisition_manifest_path)
    result = _load(bakeoff_result_path)

    if proposal.get("schema_version") != CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_PROPOSAL_SCHEMA_INVALID")
    if attestation.get("schema") != "CFB_SELECTED_CANDIDATE_BUILD_ATTESTATION_V1" or attestation.get("status") != "MODEL_PROPOSAL_BUILT_ZERO_AUTHORITY":
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_BUILD_ATTESTATION_INVALID")
    if bundle.get("schema") != "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1" or bundle.get("status") != "READY_FOR_CANDIDATE_EVALUATION":
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_SELECTION_BUNDLE_INVALID")
    if acquisition.get("schema") != "CFB_RECONSTRUCTED_ACQUISITION_READINESS_PUBLIC_V1" or acquisition.get("status") != "ACQUISITION_COMPLETE_READY_FOR_SELECTION":
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ACQUISITION_READINESS_INVALID")
    if result.get("schema") != "CFB_CANDIDATE_BAKEOFF_RESULT_V2" or result.get("status") != "WINNER_SELECTED_FOR_FREEZE":
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_WINNER_REQUIRED")

    _zero_authority(proposal.get("authority"), "proposal")
    _zero_authority(attestation.get("authority"), "attestation")
    _zero_authority(result.get("authority"), "bakeoff")
    _zero_authority(acquisition.get("authority"), "acquisition")

    result_sha = _hex64(result.get("result_sha256"), "selection_result")
    proposal_sha = _hex64(proposal.get("artifact_sha256"), "artifact")
    rows_sha = _hex64(bundle.get("selection_rows_sha256"), "selection_rows")
    source_sha = _hex64(bundle.get("source_manifest_sha256"), "source_manifest")
    predictive_sha = _hex64(bundle.get("predictive_code_manifest_sha256"), "predictive_code_manifest")
    acquisition_code_sha = _hex64(bundle.get("acquisition_code_manifest_sha256"), "acquisition_code_manifest")
    model_code_sha = cfb_selected_candidate_code_surface_sha256(repo_root)

    if canonical_sha256(source_manifest) != source_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_SOURCE_MANIFEST_HASH_MISMATCH")
    if _hex64(acquisition.get("source_manifest_sha256"), "acquisition_source_manifest") != source_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ACQUISITION_SOURCE_BINDING_MISMATCH")
    if _hex64(proposal.get("training_source_sha256"), "proposal_training_source") != rows_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_TRAINING_SOURCE_MISMATCH")
    if _hex64(proposal.get("selection_result_sha256"), "proposal_selection_result") != result_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_SELECTION_RESULT_MISMATCH")
    if _hex64(proposal.get("model_code_sha256"), "proposal_model_code") != model_code_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_MODEL_CODE_MISMATCH")

    if str(result.get("winner") or "") != str(proposal.get("candidate_family") or ""):
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_WINNER_FAMILY_MISMATCH")
    if _hex64(attestation.get("selection_rows_sha256"), "attestation_rows") != rows_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_ROWS_MISMATCH")
    if _hex64(attestation.get("source_manifest_sha256"), "attestation_source") != source_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_SOURCE_MISMATCH")
    if _hex64(attestation.get("predictive_code_manifest_sha256"), "attestation_predictive") != predictive_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_PREDICTIVE_MISMATCH")
    if _hex64(attestation.get("acquisition_code_manifest_sha256"), "attestation_acquisition") != acquisition_code_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_ACQUISITION_MISMATCH")
    if _hex64(attestation.get("selection_result_sha256"), "attestation_selection") != result_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_SELECTION_MISMATCH")
    if _hex64(attestation.get("model_code_surface_sha256"), "attestation_model_code") != model_code_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_MODEL_CODE_MISMATCH")
    if _hex64(attestation.get("model_artifact_sha256"), "attestation_artifact") != proposal_sha:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ATTESTATION_ARTIFACT_MISMATCH")

    # Re-load the proposal through the production loader after all external bindings.
    model = load_cfb_selected_candidate_artifact(
        proposal,
        expected_model_code_sha256=model_code_sha,
        expected_training_source_sha256=rows_sha,
        expected_selection_result_sha256=result_sha,
    )
    train_seasons = sorted(set(int(x) for x in model.train_seasons))
    if not train_seasons or train_seasons[-1] != 2025:
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_TRAINING_WINDOW_INVALID")

    raw = proposal_path.read_bytes()
    if sha256(raw).hexdigest() != _hex64(attestation.get("model_artifact_file_sha256"), "attestation_artifact_file"):
        raise CFBSelectedFreezeStageError("CFB_SELECTED_FREEZE_ARTIFACT_FILE_HASH_MISMATCH")

    artifact_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(proposal_path, artifact_output)
    artifact_file_sha = sha256(artifact_output.read_bytes()).hexdigest()

    evidence = {
        "schema": "CFB_SELECTED_CANDIDATE_FREEZE_EVIDENCE_V1",
        "status": "READY_FOR_SEPARATE_MAIN_FREEZE_COMMIT",
        "candidate_family": proposal["candidate_family"],
        "selection_rows_sha256": rows_sha,
        "source_manifest_sha256": source_sha,
        "predictive_code_manifest_sha256": predictive_sha,
        "acquisition_code_manifest_sha256": acquisition_code_sha,
        "selection_result_sha256": result_sha,
        "model_code_sha256": model_code_sha,
        "artifact_sha256": proposal_sha,
        "artifact_file_sha256": artifact_file_sha,
        "fit_max_season": train_seasons[-1],
        "selection_bundle": bundle,
        "source_manifest": source_manifest,
        "acquisition_readiness": acquisition,
        "bakeoff_result": result,
        "model_build_attestation": attestation,
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "eligibility": False,
            "staking": False,
            "evidence_clock": False,
            "official": False,
            "backfill": False,
        },
    }
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    evidence_text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    evidence_output.write_text(evidence_text, encoding="utf-8")
    evidence_file_sha = sha256(evidence_text.encode("utf-8")).hexdigest()

    registry = {
        "schema_version": 1,
        "sport": "CFB",
        "status": "FROZEN",
        "model_family": "CFB_SELECTED_CANDIDATE_MODEL_V1",
        "candidate_family": proposal["candidate_family"],
        "artifact_path": "models/cfb_joint_v1.json",
        "artifact_sha256": proposal_sha,
        "artifact_file_sha256": artifact_file_sha,
        "model_code_sha256": model_code_sha,
        "training_source_sha256": rows_sha,
        "source_manifest_sha256": source_sha,
        "predictive_code_manifest_sha256": predictive_sha,
        "acquisition_code_manifest_sha256": acquisition_code_sha,
        "selection_result_sha256": result_sha,
        "freeze_evidence_file_sha256": evidence_file_sha,
        "fit_max_season": train_seasons[-1],
        "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "feature_semantics": bundle.get("feature_semantics"),
        "feature_value_source_contract": bundle.get("feature_value_source_contract"),
        "promotion_authority": False,
        "evidence_clock_authority": False,
        "blocker": None,
    }
    registry_output.parent.mkdir(parents=True, exist_ok=True)
    registry_output.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "FREEZE_PR_BYTES_STAGED",
        "candidate_family": proposal["candidate_family"],
        "artifact_sha256": proposal_sha,
        "artifact_file_sha256": artifact_file_sha,
        "freeze_evidence_file_sha256": evidence_file_sha,
        "selection_result_sha256": result_sha,
        "attempts_consumed_by_this_step": 0,
        "promotion_authority": False,
        "evidence_clock_authority": False,
        "official_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-proposal", type=Path, required=True)
    ap.add_argument("--build-attestation", type=Path, required=True)
    ap.add_argument("--selection-bundle", type=Path, required=True)
    ap.add_argument("--source-manifest", type=Path, required=True)
    ap.add_argument("--acquisition-manifest", type=Path, required=True)
    ap.add_argument("--bakeoff-result", type=Path, required=True)
    ap.add_argument("--artifact-output", type=Path, default=Path("models/cfb_joint_v1.json"))
    ap.add_argument("--registry-output", type=Path, default=Path("config/cfb_game_model_freeze.json"))
    ap.add_argument("--evidence-output", type=Path, default=Path("config/cfb_selected_candidate_freeze_evidence_v1.json"))
    args = ap.parse_args(argv)
    result = stage(
        proposal_path=args.model_proposal,
        attestation_path=args.build_attestation,
        selection_bundle_path=args.selection_bundle,
        source_manifest_path=args.source_manifest,
        acquisition_manifest_path=args.acquisition_manifest,
        bakeoff_result_path=args.bakeoff_result,
        artifact_output=args.artifact_output,
        registry_output=args.registry_output,
        evidence_output=args.evidence_output,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
