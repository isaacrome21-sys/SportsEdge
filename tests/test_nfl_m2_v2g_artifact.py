import copy

import pytest

from sportsedge.sports.nfl.m2_v2g_artifact import (
    NFLV2GArtifactError,
    artifact_sha256,
    build_v2g_research_artifact,
    validate_v2g_research_artifact,
)
from sportsedge.sports.nfl.m2_v2g_candidate import NFL_M2_V2G_EVENT_CONTRACT, fit_nfl_m2_v2g_candidate


FREEZE = {
    "schema_version": "SPORTSEDGE_NFL_V2G_IMPLEMENTATION_FREEZE_V1",
    "status": "FROZEN_IMPLEMENTATION_IDENTITY",
    "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
    "distribution_contract": "NFL_M2_V2G_STRUCTURAL_SCORING_EVENT_V1",
    "event_contract": "NFL_M2_V2G_POSSESSION_EVENT_ROWS_V1",
    "implementation_commit_sha": "4dc37c4e445325c77737ec646fa37dbdbe3bfa6d",
    "candidate_source_git_blob_sha1": "4d8a3e19033b70962bec6d93d46d92a58305778e",
    "preregistration_commit_sha": "c8381b09cdde2ccbddf6787127c838d114dee994",
    "promotion_authority": False,
    "may_create_model_p": False,
}


def _rows():
    return [
        {"event_contract": NFL_M2_V2G_EVENT_CONTRACT, "game_id": "g1", "season": 2020, "home_team": "A", "away_team": "B", "home_drives": 10, "home_touchdowns": 3, "home_field_goals": 2, "home_other_no_score": 5, "away_drives": 10, "away_touchdowns": 2, "away_field_goals": 2, "away_other_no_score": 6},
        {"event_contract": NFL_M2_V2G_EVENT_CONTRACT, "game_id": "g2", "season": 2020, "home_team": "B", "away_team": "A", "home_drives": 11, "home_touchdowns": 2, "home_field_goals": 3, "home_other_no_score": 6, "away_drives": 11, "away_touchdowns": 4, "away_field_goals": 1, "away_other_no_score": 6},
    ]


def test_v2g_research_artifact_is_byte_deterministic_and_non_promotional():
    model = fit_nfl_m2_v2g_candidate(_rows())
    first = build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="1" * 64, source_manifest_sha256="2" * 64)
    second = build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="1" * 64, source_manifest_sha256="2" * 64)
    assert first == second
    assert artifact_sha256(first) == artifact_sha256(second)
    assert validate_v2g_research_artifact(first, implementation_freeze=FREEZE) == artifact_sha256(first)
    assert first["promotion_authority"] is False
    assert first["may_create_model_p"] is False
    assert first["official_status_granted"] is False


def test_v2g_artifact_sorts_team_state_for_stable_serialization():
    model = fit_nfl_m2_v2g_candidate(_rows())
    artifact = build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="a" * 64, source_manifest_sha256="b" * 64)
    assert list(artifact["model"]["team_state"]) == sorted(artifact["model"]["team_state"])


def test_v2g_artifact_rejects_unbound_or_malformed_provenance():
    model = fit_nfl_m2_v2g_candidate(_rows())
    with pytest.raises(NFLV2GArtifactError, match="training_event_rows_sha256"):
        build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="not-a-hash", source_manifest_sha256="2" * 64)


def test_v2g_artifact_rejects_freeze_identity_drift():
    model = fit_nfl_m2_v2g_candidate(_rows())
    artifact = build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="1" * 64, source_manifest_sha256="2" * 64)
    bad_freeze = copy.deepcopy(FREEZE)
    bad_freeze["implementation_commit_sha"] = "f" * 40
    with pytest.raises(NFLV2GArtifactError, match="FREEZE_BINDING_MISMATCH:implementation_commit_sha"):
        validate_v2g_research_artifact(artifact, implementation_freeze=bad_freeze)


def test_v2g_artifact_cannot_self_promote():
    model = fit_nfl_m2_v2g_candidate(_rows())
    artifact = build_v2g_research_artifact(model, implementation_freeze=FREEZE, training_event_rows_sha256="1" * 64, source_manifest_sha256="2" * 64)
    artifact["promotion_authority"] = True
    with pytest.raises(NFLV2GArtifactError, match="PROMOTION_FORBIDDEN"):
        validate_v2g_research_artifact(artifact, implementation_freeze=FREEZE)
