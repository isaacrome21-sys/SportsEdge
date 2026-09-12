import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORRECTION = ROOT / "config/research/nfl_v2g_artifact_freeze_correction_2026-09-12.json"
IMPLEMENTATION = ROOT / "config/research/nfl_v2g_implementation_freeze_2026-09-12.json"
ACTIVATION = ROOT / "config/research/nfl_v2g_prospective_activation_2026-09-12.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2g_artifact_freeze_binds_exact_implemented_identity():
    correction = _load(CORRECTION)
    implementation = _load(IMPLEMENTATION)
    activation = _load(ACTIVATION)

    assert correction["status"] == "FROZEN_RESEARCH_ARTIFACT_FOR_PROSPECTIVE_CAPTURE"
    assert correction["candidate_id"] == implementation["candidate_id"]
    assert correction["implementation_commit_sha"] == implementation["implementation_commit_sha"]
    assert correction["candidate_source_git_blob_sha1"] == implementation["candidate_source_git_blob_sha1"]
    assert correction["preregistration_commit_sha"] == implementation["preregistration_commit_sha"]
    assert correction["preregistration_timestamp_utc"] == implementation["preregistration_timestamp_utc"]

    # Preserve the historical record instead of silently rewriting the old
    # preregistration file. The correction must explicitly identify the
    # provisional id it supersedes for all future V2G evidence.
    assert activation["candidate_id"] != correction["candidate_id"]
    assert correction["supersedes_candidate_id_in_activation_file"] == activation["candidate_id"]


def test_v2g_artifact_freeze_is_hash_bound_and_non_promotional():
    correction = _load(CORRECTION)
    artifact = correction["source_bound_research_artifact"]

    for field in ("artifact_sha256", "training_event_rows_sha256", "source_manifest_sha256"):
        value = artifact[field]
        assert len(value) == 64
        int(value, 16)

    assert artifact["byte_determinism"] == "PASS"
    assert artifact["historical_data_role"] == "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT"
    assert artifact["event_row_count"] == 2639
    assert correction["artifact_freeze_may_create_model_p"] is False
    assert correction["promotion_authority"] is False
    assert correction["production_model_changed"] is False
    assert correction["market_eligibility_changed"] is False
    assert correction["official_status_granted"] is False
    assert correction["truth_gate_unchanged"] is True


def test_v2g_future_predictions_must_bind_real_artifact_not_just_preregistration():
    correction = _load(CORRECTION)
    rule = correction["prospective_prediction_rule"]
    artifact_hash = correction["source_bound_research_artifact"]["artifact_sha256"]

    assert "before kickoff" in rule
    assert "artifact_sha256" in rule
    assert artifact_hash
    assert correction["candidate_separation_rule"].startswith("V2F and V2G remain separate")
