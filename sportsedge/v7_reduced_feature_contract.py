from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .source_lineage import canonical_json_sha256
from .v7_baseball_features import assert_no_market_contamination
from .v7_feature_bundle import (
    V7_COMBINED_FEATURE_CONTRACT_SHA256,
    V7_COMBINED_FEATURE_CONTRACT_VERSION,
    get_numeric_path,
)

REDUCED_CONTRACT_ID = "SPORTSEDGE_MLB_V7_REDUCED_FEATURE_CONTRACT_V1"
DEFAULT_REDUCED_CONTRACT_PATH = Path("config/v7_reduced_feature_contract_v1.json")


class V7ReducedFeatureContractError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise V7ReducedFeatureContractError(f"REDUCED_CONTRACT_INVALID_JSON:{path}") from exc
    if not isinstance(value, dict):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_OBJECT_REQUIRED")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_hash_material(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": contract["contract"],
        "base_feature_contract_version": contract["base_feature_contract_version"],
        "base_feature_contract_sha256": contract["base_feature_contract_sha256"],
        "feature_paths": list(contract["feature_paths"]),
        "missing_value_policy": contract["missing_value_policy"],
        "projection_rule": contract["projection_rule"],
    }


def load_reduced_feature_contract(
    path: str | Path = DEFAULT_REDUCED_CONTRACT_PATH,
    *,
    policy_path: str | Path = "config/v7_feature_backfill_policy_v1.json",
    requirements_path: str | Path = "config/v7_backfill_source_requirements_v1.json",
) -> dict[str, Any]:
    path = Path(path)
    policy_path = Path(policy_path)
    requirements_path = Path(requirements_path)
    contract = _load_json(path)
    if contract.get("schema_version") != 1 or contract.get("contract") != REDUCED_CONTRACT_ID:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_ID_MISMATCH")
    if contract.get("status") != "FROZEN":
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_NOT_FROZEN")
    if contract.get("promotion_authority") is not False:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_PROMOTION_AUTHORITY_INVALID")
    if contract.get("base_feature_contract_version") != V7_COMBINED_FEATURE_CONTRACT_VERSION:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_BASE_VERSION_MISMATCH")
    if contract.get("base_feature_contract_sha256") != V7_COMBINED_FEATURE_CONTRACT_SHA256:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_BASE_SHA256_MISMATCH")
    if Path(str(contract.get("policy_path", ""))).name != policy_path.name:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_POLICY_PATH_MISMATCH")
    if Path(str(contract.get("requirements_path", ""))).name != requirements_path.name:
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_REQUIREMENTS_PATH_MISMATCH")

    paths = contract.get("feature_paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p for p in paths):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_FEATURE_PATHS_INVALID")
    if len(paths) != len(set(paths)):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_FEATURE_PATHS_DUPLICATE")

    policy = _load_json(policy_path)
    approved = policy.get("initial_backfill_approval", {}).get("approved_paths")
    if not isinstance(approved, list) or set(paths) != set(approved):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_POLICY_FEATURE_SET_MISMATCH")

    requirements = _load_json(requirements_path)
    req_paths: list[str] = []
    groups = requirements.get("groups")
    if not isinstance(groups, dict):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_REQUIREMENTS_GROUPS_INVALID")
    for group in groups.values():
        if not isinstance(group, dict) or not isinstance(group.get("feature_paths"), list):
            raise V7ReducedFeatureContractError("REDUCED_CONTRACT_REQUIREMENTS_GROUP_INVALID")
        req_paths.extend(group["feature_paths"])
    if set(paths) != set(req_paths):
        raise V7ReducedFeatureContractError("REDUCED_CONTRACT_REQUIREMENTS_FEATURE_SET_MISMATCH")

    out = deepcopy(contract)
    out["feature_paths"] = tuple(paths)
    out["feature_contract_sha256"] = canonical_json_sha256(_feature_hash_material(contract))
    out["contract_file_sha256"] = _file_sha256(path)
    return out


def project_full_payload_to_reduced(
    payload: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if str(payload.get("feature_contract_sha256") or "") != V7_COMBINED_FEATURE_CONTRACT_SHA256:
        raise V7ReducedFeatureContractError("REDUCED_PROJECTION_FULL_CONTRACT_SHA_MISMATCH")
    assert_no_market_contamination(payload)
    paths: Sequence[str] = tuple(contract.get("feature_paths") or ())
    contract_sha = str(contract.get("feature_contract_sha256") or "")
    if not paths or len(contract_sha) != 64:
        raise V7ReducedFeatureContractError("REDUCED_PROJECTION_CONTRACT_INVALID")

    projected: dict[str, Any] = {
        "feature_contract_version": REDUCED_CONTRACT_ID,
        "feature_contract_sha256": contract_sha,
    }
    if "feature_as_of_utc" in payload:
        projected["feature_as_of_utc"] = payload["feature_as_of_utc"]

    for path in paths:
        value = get_numeric_path(payload, path)
        cursor = projected
        parts = path.split(".")
        for part in parts[:-1]:
            child = cursor.get(part)
            if child is None:
                child = {}
                cursor[part] = child
            if not isinstance(child, dict):
                raise V7ReducedFeatureContractError(f"REDUCED_PROJECTION_PATH_COLLISION:{path}")
            cursor = child
        cursor[parts[-1]] = value

    assert_no_market_contamination(projected)
    projected["feature_payload_sha256"] = canonical_json_sha256(projected)
    return projected


def reduced_vector(payload: Mapping[str, Any], *, contract: Mapping[str, Any]) -> dict[str, float]:
    contract_sha = str(contract.get("feature_contract_sha256") or "")
    if str(payload.get("feature_contract_sha256") or "") != contract_sha:
        raise V7ReducedFeatureContractError("REDUCED_PAYLOAD_CONTRACT_SHA_MISMATCH")
    assert_no_market_contamination(payload)
    return {path: get_numeric_path(payload, path) for path in contract["feature_paths"]}
