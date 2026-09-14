from __future__ import annotations

import json
from pathlib import Path


CONFIG = Path("config/finish_line_blockers_v1.json")


def _payload() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_blocker_ids_are_unique_and_classified() -> None:
    payload = _payload()
    allowed = set(payload["classification_values"])
    blockers = payload["blockers"]
    ids = [row["id"] for row in blockers]
    assert len(ids) == len(set(ids))
    assert blockers
    for row in blockers:
        assert row["classification"] in allowed
        assert row["finish_condition"]


def test_public_repo_adoption_cannot_close_data_or_decision_gaps() -> None:
    payload = _payload()
    for row in payload["blockers"]:
        if row["classification"] in {"MISSING_DATA", "MISSING_DECISION"}:
            assert row["public_repo_adoption_allowed"] is False
            assert row["adoption_mode"] == "FORBIDDEN"


def test_every_external_reference_is_cataloged_and_scoped() -> None:
    payload = _payload()
    catalog = {row["repo"]: row for row in payload["public_reference_catalog"]}
    assert catalog
    for repo, row in catalog.items():
        assert "/" in repo
        assert row["approved_scope"]
        assert row["forbidden_scope"]
    for blocker in payload["blockers"]:
        for repo in blocker.get("reference_repos", []):
            assert repo in catalog
            assert blocker["classification"] == "MISSING_IMPLEMENTATION"
            assert blocker["public_repo_adoption_allowed"] is True


def test_external_model_logic_is_challenger_or_plumbing_only() -> None:
    payload = _payload()
    rules = payload["rules"]
    assert rules["evidence_facing_external_model_logic_enters_as_challenger_only"] is True
    assert rules["external_calibration_or_prior_authority_forbidden"] is True
    assert rules["external_historical_windows_do_not_establish_pit"] is True
    assert rules["external_repo_results_do_not_establish_provenance"] is True
    assert rules["public_reference_must_name_exact_repo_and_scope"] is True

    mlb = next(row for row in payload["blockers"] if row["id"] == "MLB_DFS_ENDOGENOUS_JOINT_PATH_PRODUCER")
    assert mlb["classification"] == "MISSING_IMPLEMENTATION"
    assert mlb["public_repo_adoption_allowed"] is True
    assert mlb["adoption_mode"] == "CHALLENGER_ONLY"
    forbidden = set(mlb["forbidden_reference_scope"])
    assert {
        "external_fitted_probabilities",
        "external_calibration",
        "external_training_windows",
        "external_readiness_claims",
    }.issubset(forbidden)

    for blocker_id in (
        "NFL_PLAYER_PROP_PROBABILITY_ENGINE",
        "CFB_PLAYER_PARTICIPATION_AND_PROP_ENGINE",
        "DFS_FIELD_DUPLICATION_AND_CONTEST_EV_SIMULATION",
    ):
        row = next(item for item in payload["blockers"] if item["id"] == blocker_id)
        assert row["classification"] == "MISSING_IMPLEMENTATION"
        assert row["adoption_mode"] == "PLUMBING_ONLY"
        assert row["reference_repos"]
        assert row["forbidden_reference_scope"]


def test_prop_runtime_gaps_are_not_hidden_by_data_plumbing() -> None:
    payload = _payload()
    states = {row["id"]: row["state"] for row in payload["blockers"]}
    assert states["NFL_PLAYER_PROP_PROBABILITY_ENGINE"] == "NO_ENGINE"
    assert states["CFB_PLAYER_PARTICIPATION_AND_PROP_ENGINE"] == "NO_ENGINE_PARTICIPATION_LAYER_REQUIRED"
    evidence = next(row for row in payload["blockers"] if row["id"] == "FOOTBALL_PROP_FORWARD_PIT_AND_VALIDATION_EVIDENCE")
    assert evidence["classification"] == "MISSING_DATA"
    assert evidence["public_repo_adoption_allowed"] is False


def test_plumbing_cannot_change_evidence_semantics() -> None:
    payload = _payload()
    assert payload["rules"]["plumbing_adoption_may_not_change_evidence_semantics"] is True
    assert payload["rules"]["no_model_p_or_truth_gate_or_official_authority"] is True
