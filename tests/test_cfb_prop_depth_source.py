from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile

import pytest

from sportsedge.sports.cfb.depth_chart_source import (
    CFBDepthSourceError,
    CORROBORATION_SOURCE_ID,
    POLICY_PATH,
    POLICY_SHA256,
    content_sha256,
    load_depth_source_policy,
    require_player_depth_usable,
    validate_depth_snapshot,
)


RAW = b"<html><body>point-in-time depth chart bytes</body></html>"
DIGEST = content_sha256(RAW)


def _snapshot():
    return {
        "source_id": "TWO_DEEP_PROJECTED_TWO_DEEP",
        "source_kind": "PROJECTED_TWO_DEEP",
        "retrieved_at": "2026-09-11T15:00:00Z",
        "source_updated_at": "2026-09-10",
        "source_url": "https://www.thetwodeep.com/college/alabama",
        "content_sha256": DIGEST,
        "team_id": "alabama",
        "players": [
            {
                "player_id": "daniel-hill",
                "position": "RB",
                "depth_rank": 1,
                "unavailable": False,
            }
        ],
    }


def _validate(row=None, **overrides):
    kwargs = {
        "previous_game_end": "2026-09-06T03:00:00Z",
        "decision_time": "2026-09-11T16:00:00Z",
        "target_game_start": "2026-09-12T00:00:00Z",
        "expected_team_id": "alabama",
        "expected_content_sha256": DIGEST,
    }
    kwargs.update(overrides)
    return validate_depth_snapshot(row or _snapshot(), **kwargs)


def test_policy_bytes_are_runtime_authority_and_nonactivating():
    assert POLICY_SHA256 == sha256(POLICY_PATH.read_bytes()).hexdigest()
    policy = load_depth_source_policy()
    assert policy["status"] == "CANDIDATE_INPUT_ONLY"
    assert policy["promotion_authority"] is False
    assert policy["model_p_authority"] is False
    assert policy["primary_source"]["automated_acquisition"] is False
    assert policy["corroboration"]["automated_acquisition"] is False


def test_config_only_activation_fails_closed():
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["status"] = "ACTIVE"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "policy.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(CFBDepthSourceError, match="ACTIVATION_REQUIRES_CODE_REVIEW"):
            load_depth_source_policy(path)


def test_snapshot_accepts_only_pit_team_and_hash_bound_input():
    row = _validate()
    assert row["point_in_time_validated"] is True
    assert row["policy_sha256"] == POLICY_SHA256
    assert row["team_id"] == "alabama"
    assert row["content_sha256"] == DIGEST
    assert row["promotion_authority"] is False
    assert row["model_p_authority"] is False


def test_snapshot_blocks_stale_chart():
    row = _snapshot()
    row["source_updated_at"] = "2026-09-05"
    with pytest.raises(CFBDepthSourceError, match="DEPTH_CHART_STALE"):
        _validate(row)


def test_snapshot_blocks_postdecision_retrieval():
    row = _snapshot()
    row["retrieved_at"] = "2026-09-11T16:00:01Z"
    with pytest.raises(CFBDepthSourceError, match="CFB_DEPTH_RETRIEVED_AFTER_DECISION"):
        _validate(row)


def test_snapshot_blocks_decision_at_or_after_kickoff():
    with pytest.raises(CFBDepthSourceError, match="CFB_DEPTH_DECISION_NOT_PREGAME"):
        _validate(decision_time="2026-09-12T00:00:00Z")


def test_snapshot_blocks_wrong_team_binding():
    with pytest.raises(CFBDepthSourceError, match="CFB_DEPTH_TEAM_ID_MISMATCH"):
        _validate(expected_team_id="georgia")


def test_snapshot_blocks_hash_mismatch():
    with pytest.raises(CFBDepthSourceError, match="CFB_DEPTH_CONTENT_SHA256_MISMATCH"):
        _validate(expected_content_sha256="b" * 64)


def test_unavailable_player_blocks():
    player = dict(_snapshot()["players"][0])
    player["unavailable"] = True
    with pytest.raises(CFBDepthSourceError, match="PLAYER_UNAVAILABLE"):
        require_player_depth_usable(
            primary_player=player,
            corroborating_source_id=CORROBORATION_SOURCE_ID,
            corroborating_starter_player_id="daniel-hill",
        )


def test_unapproved_corroboration_source_blocks():
    player = _snapshot()["players"][0]
    with pytest.raises(CFBDepthSourceError, match="CFB_DEPTH_CORROBORATION_SOURCE_INVALID"):
        require_player_depth_usable(
            primary_player=player,
            corroborating_source_id="UNVERIFIED_SOURCE",
            corroborating_starter_player_id="daniel-hill",
        )


def test_starter_conflict_blocks():
    player = _snapshot()["players"][0]
    with pytest.raises(CFBDepthSourceError, match="STARTER_CONFLICT"):
        require_player_depth_usable(
            primary_player=player,
            corroborating_source_id=CORROBORATION_SOURCE_ID,
            corroborating_starter_player_id="other-player",
        )
