from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from sportsedge.v7_feature_bundle import V7_COMBINED_FEATURE_CONTRACT_SHA256
from sportsedge.v7_reduced_feature_contract import (
    V7ReducedFeatureContractError,
    load_reduced_feature_contract,
    project_full_payload_to_reduced,
    reduced_vector,
)
from sportsedge.v7_training import V7TrainingError, train_chronological_candidate


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "v7_reduced_feature_contract_v1.json"
POLICY_PATH = ROOT / "config" / "v7_feature_backfill_policy_v1.json"
REQUIREMENTS_PATH = ROOT / "config" / "v7_backfill_source_requirements_v1.json"


def _set_path(payload: dict, path: str, value: float) -> None:
    cursor = payload
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _full_payload(contract: dict, seed: int) -> dict:
    payload = {
        "feature_contract_version": "mlb_v7_combined_feature_contract_v1",
        "feature_contract_sha256": V7_COMBINED_FEATURE_CONTRACT_SHA256,
        "feature_as_of_utc": f"2024-01-{(seed % 20) + 1:02d}T12:00:00+00:00",
        "baseball": {},
        "context": {},
        "ignored_metadata": "discard-me",
    }
    for idx, path in enumerate(contract["feature_paths"]):
        _set_path(payload, path, float(seed + idx + 1))
    return payload


def test_frozen_reduced_contract_matches_exact_policy_approval() -> None:
    contract = load_reduced_feature_contract(
        CONTRACT_PATH,
        policy_path=POLICY_PATH,
        requirements_path=REQUIREMENTS_PATH,
    )
    assert len(contract["feature_paths"]) == 12
    assert len(contract["feature_contract_sha256"]) == 64
    assert len(contract["contract_file_sha256"]) == 64
    assert contract["promotion_authority"] is False


def test_projection_changes_contract_identity_and_keeps_only_frozen_paths() -> None:
    contract = load_reduced_feature_contract(
        CONTRACT_PATH,
        policy_path=POLICY_PATH,
        requirements_path=REQUIREMENTS_PATH,
    )
    projected = project_full_payload_to_reduced(_full_payload(contract, 3), contract=contract)
    vector = reduced_vector(projected, contract=contract)
    assert projected["feature_contract_sha256"] == contract["feature_contract_sha256"]
    assert projected["feature_contract_sha256"] != V7_COMBINED_FEATURE_CONTRACT_SHA256
    assert "ignored_metadata" not in projected
    assert set(vector) == set(contract["feature_paths"])


def test_projection_rejects_payload_not_bound_to_full_contract() -> None:
    contract = load_reduced_feature_contract(
        CONTRACT_PATH,
        policy_path=POLICY_PATH,
        requirements_path=REQUIREMENTS_PATH,
    )
    payload = _full_payload(contract, 1)
    payload["feature_contract_sha256"] = "0" * 64
    with pytest.raises(V7ReducedFeatureContractError, match="FULL_CONTRACT_SHA_MISMATCH"):
        project_full_payload_to_reduced(payload, contract=contract)


def test_trainer_stamps_reduced_contract_and_only_twelve_coefficients() -> None:
    contract = load_reduced_feature_contract(
        CONTRACT_PATH,
        policy_path=POLICY_PATH,
        requirements_path=REQUIREMENTS_PATH,
    )
    rows = []
    start = date(2023, 1, 1)
    for idx in range(10):
        rows.append({
            "game_date": (start + timedelta(days=idx)).isoformat(),
            "outcome": idx % 2,
            "feature_payload": project_full_payload_to_reduced(_full_payload(contract, idx), contract=contract),
        })
    for idx in range(2):
        rows.append({
            "game_date": date(2024, 1, idx + 1).isoformat(),
            "outcome": idx,
            "feature_payload": project_full_payload_to_reduced(_full_payload(contract, 20 + idx), contract=contract),
        })

    artifact, report = train_chronological_candidate(
        rows,
        model_name="V7_REDUCED_TEST",
        train_end="2023-12-31",
        calibration_start="2024-01-01",
        calibration_end="2024-12-31",
        holdout_start="2025-01-01",
        feature_paths=contract["feature_paths"],
        feature_contract_sha256=contract["feature_contract_sha256"],
        iterations=5,
        learning_rate=0.05,
    )

    assert artifact["feature_contract_sha256"] == contract["feature_contract_sha256"]
    assert set(artifact["coefficients"]) == set(contract["feature_paths"])
    assert len(artifact["coefficients"]) == 12
    assert report["feature_contract_sha256"] == contract["feature_contract_sha256"]
    assert report["feature_paths"] == list(contract["feature_paths"])


def test_trainer_rejects_reduced_paths_with_full_contract_hash() -> None:
    contract = load_reduced_feature_contract(
        CONTRACT_PATH,
        policy_path=POLICY_PATH,
        requirements_path=REQUIREMENTS_PATH,
    )
    rows = [{
        "game_date": f"2023-01-{idx + 1:02d}",
        "outcome": idx % 2,
        "feature_payload": project_full_payload_to_reduced(_full_payload(contract, idx), contract=contract),
    } for idx in range(10)]
    rows.extend([
        {"game_date": "2024-01-01", "outcome": 0, "feature_payload": project_full_payload_to_reduced(_full_payload(contract, 30), contract=contract)},
        {"game_date": "2024-01-02", "outcome": 1, "feature_payload": project_full_payload_to_reduced(_full_payload(contract, 31), contract=contract)},
    ])
    with pytest.raises(V7TrainingError, match="contract hash mismatch"):
        train_chronological_candidate(
            rows,
            model_name="BAD_BINDING",
            train_end="2023-12-31",
            calibration_start="2024-01-01",
            calibration_end="2024-12-31",
            holdout_start="2025-01-01",
            feature_paths=contract["feature_paths"],
            feature_contract_sha256=V7_COMBINED_FEATURE_CONTRACT_SHA256,
            iterations=5,
        )
