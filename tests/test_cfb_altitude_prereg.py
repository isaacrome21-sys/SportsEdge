from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from sportsedge.sports.cfb.altitude_prereg import (
    EXPECTED_CANDIDATES,
    EXPECTED_SOURCE_SCHEMA_COMMIT,
    audit_altitude_policy,
    verify_altitude_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "cfb_altitude_challenger_policy_v1.json"
FROZEN_V1_PATH = ROOT / "config" / "cfb_model_selection_policy_v1.json"


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_altitude_policy_is_frozen_separate_and_unevaluated() -> None:
    audit = audit_altitude_policy(_policy())
    assert audit["status"] == "READY_TO_BIND_SNAPSHOT"
    assert audit["blockers"] == []
    assert audit["candidate_attempt_budget"] == 3
    assert audit["attempts_consumed"] == 0
    assert tuple(audit["candidate_ids"]) == EXPECTED_CANDIDATES
    assert audit["fit_performed"] is False
    assert audit["evaluation_performed"] is False
    assert audit["attempt_consumed_by_this_audit"] is False
    assert audit["model_p_created"] is False
    assert audit["promotion_authority"] is False
    assert audit["official_authority"] is False


def test_existing_frozen_v1_search_is_not_extended_with_altitude() -> None:
    frozen = json.loads(FROZEN_V1_PATH.read_text(encoding="utf-8"))
    assert frozen["schema"] == "CFB_MODEL_SELECTION_POLICY_V1"
    assert frozen["status"] == "FROZEN_BEFORE_CANDIDATE_EVALUATION"
    assert frozen["candidate_attempt_budget"] == 4
    assert frozen["attempts_consumed"] == 0
    assert len(frozen["candidate_families_predeclared"]) == 4
    assert not any("ALTITUDE" in family.upper() for family in frozen["candidate_families_predeclared"])


def test_policy_fails_closed_if_market_or_2026_selection_is_enabled() -> None:
    policy = _policy()
    policy["governance"]["market_data_allowed"] = True
    policy["governance"]["season_2026_allowed_for_fit_tune_or_selection"] = True
    audit = audit_altitude_policy(policy)
    assert audit["status"] == "BLOCKED_ALTITUDE_PREREG"
    assert "MARKET_INPUTS_MUST_BE_DISABLED" in audit["blockers"]
    assert "SEASON_2026_MUST_BE_EXCLUDED" in audit["blockers"]


def test_policy_fails_closed_if_candidate_formula_is_mutated() -> None:
    policy = deepcopy(_policy())
    policy["feature_contract"]["candidates"][0]["fixed_constants"]["cap_ft"] = 7000
    audit = audit_altitude_policy(policy)
    assert audit["status"] == "BLOCKED_ALTITUDE_PREREG"
    assert "CANDIDATE_SPEC_MUTATED" in audit["blockers"]


def test_policy_pins_public_cfbd_schema_commit() -> None:
    policy = _policy()
    assert policy["source_contract"]["schema_commit_sha"] == EXPECTED_SOURCE_SCHEMA_COMMIT
    mutated = deepcopy(policy)
    mutated["source_contract"]["schema_commit_sha"] = "0" * 40
    audit = audit_altitude_policy(mutated)
    assert "SOURCE_SCHEMA_COMMIT_MISMATCH" in audit["blockers"]


def test_snapshot_binding_hashes_bytes_without_fitting(tmp_path: Path) -> None:
    policy = _policy()
    snapshot = tmp_path / "cfb_altitude_static_v1.jsonl"
    payload = b'{"entity_type":"venue","id":1,"elevation":5280}\n'
    snapshot.write_bytes(payload)
    manifest = {
        "source_provider": "CollegeFootballData",
        "source_schema_commit_sha": EXPECTED_SOURCE_SCHEMA_COMMIT,
        "retrieved_at_utc": "2026-09-27T00:00:00Z",
        "record_count": 1,
        "content_sha256": sha256(payload).hexdigest(),
    }
    result = verify_altitude_snapshot(policy=policy, manifest=manifest, snapshot_path=snapshot)
    assert result["status"] == "SNAPSHOT_BOUND_NO_EVALUATION"
    assert result["blockers"] == []
    assert result["content_sha256"] == manifest["content_sha256"]
    assert result["fit_performed"] is False
    assert result["evaluation_performed"] is False
    assert result["attempt_consumed_by_this_verifier"] is False
    assert result["model_p_created"] is False
    assert result["promotion_authority"] is False
    assert result["official_authority"] is False


def test_snapshot_binding_fails_closed_on_byte_mutation(tmp_path: Path) -> None:
    policy = _policy()
    snapshot = tmp_path / "cfb_altitude_static_v1.jsonl"
    original = b'{"entity_type":"venue","id":1,"elevation":5280}\n'
    snapshot.write_bytes(original)
    manifest = {
        "source_provider": "CollegeFootballData",
        "source_schema_commit_sha": EXPECTED_SOURCE_SCHEMA_COMMIT,
        "retrieved_at_utc": "2026-09-27T00:00:00Z",
        "record_count": 1,
        "content_sha256": sha256(original).hexdigest(),
    }
    snapshot.write_bytes(b'{"entity_type":"venue","id":1,"elevation":0}\n')
    result = verify_altitude_snapshot(policy=policy, manifest=manifest, snapshot_path=snapshot)
    assert result["status"] == "BLOCKED_ALTITUDE_SNAPSHOT"
    assert "SNAPSHOT_SHA256_MISMATCH" in result["blockers"]
