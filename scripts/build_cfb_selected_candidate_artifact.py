#!/usr/bin/env python3
"""Build a zero-authority CFB selected-candidate model proposal after the frozen bakeoff.

This script performs no candidate search and consumes no additional attempt. The
winner and its final ridge alpha are determined entirely by pre-evaluation frozen
artifacts. The output is a hash-bound model proposal only; it cannot activate a
freeze, start an evidence clock, create Model_P, pass Truth Gate, promote a market,
stake, backfill, or authorize an OFFICIAL bet.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.selected_candidate_artifact import (
    build_cfb_selected_candidate_artifact,
    cfb_selected_candidate_code_surface_sha256,
)
from sportsedge.sports.cfb.selected_candidate_model import (
    fit_cfb_selected_candidate_score_model,
)

POLICY = ROOT / "config/cfb_selected_candidate_final_fit_policy_v1.json"


class CFBSelectedCandidateBuildError(ValueError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise CFBSelectedCandidateBuildError(f"CFB_SELECTED_BUILD_JSON_INVALID:{path}") from exc


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _hex64(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBSelectedCandidateBuildError(f"{name}_INVALID")
    return text


def _verify_result(result: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[str, float, str]:
    if result.get("schema") != policy.get("required_bakeoff_schema"):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_BAKEOFF_SCHEMA_INVALID")
    if result.get("status") != policy.get("required_bakeoff_status"):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_NO_FROZEN_WINNER")
    winner = str(result.get("winner") or "").strip()
    if not winner:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_WINNER_MISSING")
    authority = result.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_BAKEOFF_AUTHORITY_LEAK")

    claimed = _hex64(result.get("result_sha256"), "CFB_SELECTED_BUILD_RESULT_SHA256")
    unhashed = dict(result)
    unhashed.pop("result_sha256", None)
    if _hash(unhashed) != claimed:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_RESULT_HASH_MISMATCH")

    expected_season = int(policy.get("latest_outer_validation_season"))
    observed = result.get("observed")
    if not isinstance(observed, Mapping) or not isinstance(observed.get(winner), Mapping):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_WINNER_OBSERVED_MISSING")
    folds = observed[winner].get("folds")
    if not isinstance(folds, list):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_WINNER_FOLDS_MISSING")
    matching = [fold for fold in folds if isinstance(fold, Mapping) and int(fold.get("season", -1)) == expected_season]
    if len(matching) != 1:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_FINAL_ALPHA_FOLD_INVALID")
    try:
        alpha = float(matching[0]["alpha"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_FINAL_ALPHA_INVALID") from exc
    if alpha < 0:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_FINAL_ALPHA_INVALID")
    return winner, alpha, claimed


def build_from_inputs(
    *,
    rows: list[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    result: Mapping[str, Any],
    policy: Mapping[str, Any],
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if policy.get("schema") != "CFB_SELECTED_CANDIDATE_FINAL_FIT_POLICY_V1":
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_POLICY_SCHEMA_INVALID")
    if policy.get("status") != "FROZEN_BEFORE_FIRST_EVALUATION":
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_POLICY_NOT_FROZEN_PRE_EVAL")
    if policy.get("ridge_alpha_rule") != "USE_SELECTED_FAMILY_ALPHA_FROM_LATEST_OUTER_FOLD":
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_ALPHA_RULE_INVALID")
    if policy.get("post_result_retuning_allowed") is not False or policy.get("alternate_alpha_selection_after_bakeoff_allowed") is not False:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_POST_RESULT_RETUNING_NOT_PROHIBITED")
    policy_authority = policy.get("authority")
    if not isinstance(policy_authority, Mapping) or any(value is not False for value in policy_authority.values()):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_POLICY_AUTHORITY_LEAK")

    if not isinstance(rows, list) or not rows:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_ROWS_MISSING")
    rows_sha = _hash(rows)
    expected_rows_sha = _hex64(bundle.get("selection_rows_sha256"), "CFB_SELECTED_BUILD_BUNDLE_ROWS_SHA256")
    if rows_sha != expected_rows_sha:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_SELECTION_ROWS_HASH_MISMATCH")
    if _hex64(result.get("rows_sha256"), "CFB_SELECTED_BUILD_RESULT_ROWS_SHA256") != rows_sha:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_RESULT_ROWS_BINDING_MISMATCH")

    input_identity = result.get("input_identity")
    if not isinstance(input_identity, Mapping):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_INPUT_IDENTITY_MISSING")
    for key in (
        "selection_rows_sha256",
        "source_manifest_sha256",
        "predictive_code_manifest_sha256",
        "acquisition_code_manifest_sha256",
    ):
        if str(input_identity.get(key) or "") != str(bundle.get(key) or ""):
            raise CFBSelectedCandidateBuildError(f"CFB_SELECTED_BUILD_INPUT_IDENTITY_MISMATCH:{key}")

    winner, alpha, result_sha = _verify_result(result, policy)
    model = fit_cfb_selected_candidate_score_model(rows, family=winner, ridge_alpha=alpha)
    if policy.get("require_nonempty_overtime_profile") is True and not model.overtime_deltas:
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_OVERTIME_PROFILE_EMPTY")

    model_code_sha = cfb_selected_candidate_code_surface_sha256(repo_root)
    artifact = build_cfb_selected_candidate_artifact(
        model,
        model_code_sha256=model_code_sha,
        training_source_sha256=rows_sha,
        selection_result_sha256=result_sha,
    )
    if any(value is not False for value in artifact.get("authority", {}).values()):
        raise CFBSelectedCandidateBuildError("CFB_SELECTED_BUILD_ARTIFACT_AUTHORITY_LEAK")

    policy_path = repo_root / "config/cfb_selected_candidate_final_fit_policy_v1.json"
    policy_file_sha = sha256(policy_path.read_bytes()).hexdigest()
    attestation = {
        "schema": "CFB_SELECTED_CANDIDATE_BUILD_ATTESTATION_V1",
        "status": "MODEL_PROPOSAL_BUILT_ZERO_AUTHORITY",
        "candidate_family": winner,
        "final_ridge_alpha": alpha,
        "final_alpha_rule": policy.get("ridge_alpha_rule"),
        "final_alpha_source_season": int(policy.get("latest_outer_validation_season")),
        "selection_rows_sha256": rows_sha,
        "source_manifest_sha256": bundle.get("source_manifest_sha256"),
        "predictive_code_manifest_sha256": bundle.get("predictive_code_manifest_sha256"),
        "acquisition_code_manifest_sha256": bundle.get("acquisition_code_manifest_sha256"),
        "selection_result_sha256": result_sha,
        "final_fit_policy_file_sha256": policy_file_sha,
        "model_code_surface_sha256": model_code_sha,
        "model_artifact_sha256": artifact.get("artifact_sha256"),
        "train_seasons": list(model.train_seasons),
        "training_rows": len(rows),
        "overtime_profile_games": len(model.overtime_deltas),
        "activation_required": "SEPARATE_REFS_HEADS_MAIN_FREEZE_COMMIT_BINDING_EXACT_ARTIFACT_AND_MANIFESTS",
        "authority": {
            "attempt_consumed": False,
            "evaluation_performed": False,
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
    return artifact, attestation


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-rows", type=Path, required=True)
    ap.add_argument("--selection-bundle", type=Path, required=True)
    ap.add_argument("--bakeoff-result", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--attestation-out", type=Path, required=True)
    args = ap.parse_args(argv)

    rows = _load(args.private_rows)
    bundle = _load(args.selection_bundle)
    result = _load(args.bakeoff_result)
    policy = _load(POLICY)
    artifact, attestation = build_from_inputs(
        rows=rows,
        bundle=bundle,
        result=result,
        policy=policy,
        repo_root=ROOT,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.attestation_out.parent.mkdir(parents=True, exist_ok=True)
    artifact_text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    args.out.write_text(artifact_text)
    attestation["model_artifact_file_sha256"] = sha256(artifact_text.encode("utf-8")).hexdigest()
    args.attestation_out.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": attestation["status"],
        "candidate_family": attestation["candidate_family"],
        "final_ridge_alpha": attestation["final_ridge_alpha"],
        "model_artifact_sha256": attestation["model_artifact_sha256"],
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "staking_authority": False,
        "evidence_clock_authority": False,
        "official_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
