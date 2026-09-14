from __future__ import annotations

import json
from pathlib import Path


CONFIG = Path("config/finish_line_blockers_v2.json")


def _payload() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _by_id(payload: dict, blocker_id: str) -> dict:
    return next(row for row in payload["blockers"] if row["id"] == blocker_id)


def test_blocker_ids_are_unique_and_all_classifications_are_declared() -> None:
    payload = _payload()
    allowed = set(payload["classification_values"])
    blockers = payload["blockers"]
    ids = [row["id"] for row in blockers]
    assert blockers
    assert len(ids) == len(set(ids))
    for row in blockers:
        classifications = row["classifications"]
        assert classifications
        assert set(classifications).issubset(allowed)
        assert row["finish_condition"]


def test_public_repo_adoption_can_close_only_implementation_gaps() -> None:
    payload = _payload()
    for row in payload["blockers"]:
        nonimplementation = set(row["classifications"]) - {"MISSING_IMPLEMENTATION"}
        if nonimplementation and "MISSING_IMPLEMENTATION" not in row["classifications"]:
            assert row["public_repo_adoption_allowed"] is False
            assert row["adoption_mode"] == "FORBIDDEN"


def test_contest_ev_has_independent_implementation_and_evidence_blocks() -> None:
    payload = _payload()
    row = _by_id(payload, "DFS_FIELD_DUPLICATION_AND_CONTEST_EV_SIMULATION")
    assert set(row["classifications"]) == {"MISSING_IMPLEMENTATION", "MISSING_EVIDENCE"}
    assert row["implementation_state"].startswith("MISSING_")
    assert row["evidence_state"] == "MISSING_REALIZED_OWNERSHIP_CALIBRATION"
    assert row["activation_guard"] == "CONTEST_EV_BLOCKED_UNTIL_REALIZED_OWNERSHIP_EVIDENCE_MATURE"
    assert row["dependency_blocker_ids"] == ["DK_REALIZED_OWNERSHIP_EVIDENCE"]
    assert payload["rules"]["synthetic_ownership_cannot_unblock_contest_ev"] is True
    assert payload["rules"]["implementation_complete_does_not_imply_lane_complete"] is True


def test_dk_ownership_is_user_action_evidence_not_external_adoption() -> None:
    payload = _payload()
    row = _by_id(payload, "DK_REALIZED_OWNERSHIP_EVIDENCE")
    assert row["classifications"] == ["MISSING_EVIDENCE"]
    assert row["state"] == "NOT_ACCRUING_UNTIL_CONTEST_ENTRY_AND_EXPORT"
    assert row["user_action_required"] is True
    assert row["public_repo_adoption_allowed"] is False


def test_branch_protection_is_permission_not_evidence_or_decision() -> None:
    payload = _payload()
    row = _by_id(payload, "MAIN_REQUIRED_STATUS_CHECK_PROTECTION")
    assert row["classifications"] == ["MISSING_PERMISSION"]
    assert row["state"] == "REPOSITORY_ADMIN_PERMISSION_REQUIRED"
    assert row["observed_repository_rulesets"] == 0
    assert row["assistant_connection_can_administer_rulesets"] is False


def test_terminal_insufficient_evidence_is_explicit() -> None:
    payload = _payload()
    terminal = {
        "MLB_CFB_HISTORICAL_CLOSING_LINE_EVIDENCE",
        "CFB_HISTORICAL_PIT_FEATURE_VINTAGES",
        "FOOTBALL_PROP_FORWARD_PIT_AND_VALIDATION_EVIDENCE",
        "NFL_V2K_FRESH_UNTOUCHED_READOUT",
    }
    for blocker_id in terminal:
        row = _by_id(payload, blocker_id)
        assert row["classifications"] == ["MISSING_EVIDENCE"]
        assert row["state"] == "INSUFFICIENT_EVIDENCE"
        assert row["public_repo_adoption_allowed"] is False


def test_external_dfs_simulators_are_reference_only_and_cannot_supply_ownership() -> None:
    payload = _payload()
    catalog = {row["repo"]: row for row in payload["public_reference_catalog"]}
    for repo in ("tburger101/dfs_simulator", "chanzer0/MLB-DFS-Tools"):
        row = catalog[repo]
        assert row["license/use"] == "REFERENCE_ONLY_NO_DATA_TRANSFER"
        forbidden = set(row["forbidden_scope"])
        assert any("ownership" in value for value in forbidden)
        assert any("ev" in value or "roi" in value for value in forbidden)


def test_every_reference_is_cataloged_and_evidence_semantics_do_not_transfer() -> None:
    payload = _payload()
    catalog = {row["repo"] for row in payload["public_reference_catalog"]}
    for blocker in payload["blockers"]:
        for repo in blocker.get("reference_repos", []):
            assert repo in catalog
            assert "MISSING_IMPLEMENTATION" in blocker["classifications"]
            assert blocker["public_repo_adoption_allowed"] is True
    rules = payload["rules"]
    assert rules["plumbing_adoption_may_not_change_evidence_semantics"] is True
    assert rules["external_calibration_or_prior_authority_forbidden"] is True
    assert rules["external_repo_results_do_not_establish_provenance"] is True
    assert rules["no_model_p_or_truth_gate_or_official_authority"] is True
