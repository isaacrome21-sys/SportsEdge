import hashlib
import json
from pathlib import Path

from sportsedge.sports.nfl.m2_v2g_candidate import (
    NFL_M2_V2G_CANDIDATE_MODEL_ID,
    NFL_M2_V2G_DISTRIBUTION_CONTRACT,
    NFL_M2_V2G_EVENT_CONTRACT,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "config/research/nfl_v2g_implementation_freeze_2026-09-12.json"


def _git_blob_sha1(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def test_v2g_implementation_freeze_matches_checked_out_source():
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    source = ROOT / frozen["candidate_source_path"]
    raw = source.read_bytes()

    assert frozen["schema_version"] == "SPORTSEDGE_NFL_V2G_IMPLEMENTATION_FREEZE_V1"
    assert frozen["status"] == "FROZEN_IMPLEMENTATION_IDENTITY"
    assert frozen["candidate_id"] == NFL_M2_V2G_CANDIDATE_MODEL_ID
    assert frozen["distribution_contract"] == NFL_M2_V2G_DISTRIBUTION_CONTRACT
    assert frozen["event_contract"] == NFL_M2_V2G_EVENT_CONTRACT
    assert _git_blob_sha1(raw) == frozen["candidate_source_git_blob_sha1"]
    assert len(frozen["implementation_commit_sha"]) == 40
    assert len(frozen["preregistration_commit_sha"]) == 40


def test_v2g_freeze_remains_non_promotional_without_artifact():
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert frozen["artifact_status"] == "NOT_YET_FROZEN"
    assert frozen["artifact_missing_status"] == "BLOCKED_MISSING_V2G_MODEL_ARTIFACT"
    assert frozen["promotion_authority"] is False
    assert frozen["production_model_changed"] is False
    assert frozen["market_eligibility_changed"] is False
    assert frozen["may_create_model_p"] is False
    assert frozen["official_status_granted"] is False
    assert frozen["truth_gate_unchanged"] is True
