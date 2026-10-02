from __future__ import annotations

from hashlib import sha256

import pytest

from sportsedge.sports.cfb.altitude_dataset import (
    CFBAltitudeDatasetError,
    build_altitude_dataset_manifest,
)
from sportsedge.sports.cfb.altitude_snapshot import canonical_jsonl


def _snapshot_records():
    return [
        {"entity_type": "team", "id": 10, "school": "Away", "location": {"id": 100, "elevation_ft": 1000.0}},
        {"entity_type": "team", "id": 20, "school": "Home", "location": {"id": 200, "elevation_ft": 500.0}},
        {"entity_type": "venue", "id": 100, "name": "Away Field", "elevation_ft": 1000.0},
        {"entity_type": "venue", "id": 200, "name": "Home Field", "elevation_ft": 500.0},
        {"entity_type": "venue", "id": 999, "name": "Mountain Bowl", "elevation_ft": 5280.0},
    ]


def _snapshot_manifest_and_binding():
    snapshot_sha = sha256(canonical_jsonl(_snapshot_records())).hexdigest()
    manifest = {
        "source_provider": "CollegeFootballData",
        "source_schema_commit_sha": "06dbcb5a7977470c3b6296f1f18c9df64676876f",
        "source_mirror_repository": "mirror/repo",
        "source_mirror_commit_sha": "1" * 40,
        "source_mirror_path": "data.csv",
        "source_mirror_git_blob_sha1": "2" * 40,
        "source_content_sha256": "3" * 64,
        "content_sha256": snapshot_sha,
        "record_count": 5,
        "stats": {
            "source_rows": 2,
            "team_records": 2,
            "venue_records": 3,
            "teams_missing_venue": 0,
            "teams_missing_elevation": 0,
            "venues_missing_elevation": 0,
        },
    }
    binding = {
        "source_provider": manifest["source_provider"],
        "source_schema_commit_sha": manifest["source_schema_commit_sha"],
        "source_mirror_repository": manifest["source_mirror_repository"],
        "source_mirror_commit_sha": manifest["source_mirror_commit_sha"],
        "source_mirror_path": manifest["source_mirror_path"],
        "source_mirror_git_blob_sha1": manifest["source_mirror_git_blob_sha1"],
        "source_content_sha256": manifest["source_content_sha256"],
        "snapshot_content_sha256": manifest["content_sha256"],
        "snapshot_record_count": manifest["record_count"],
        **manifest["stats"],
        "governance": {
            "fit_performed": False,
            "evaluation_performed": False,
            "attempt_consumed": False,
            "attempts_used": 0,
            "attempts_max": 3,
            "model_p_created": False,
            "truth_gate_authority": False,
            "promotion_authority": False,
            "official_authority": False,
        },
    }
    return manifest, binding


def _baseline(game_id="g1", season=2025):
    return {
        "game_id": game_id,
        "season": season,
        "week": 5,
        "historical_pit_created": True,
        "provenance_class": "PRE_EVENT_ARCHIVE",
        "home_metrics": {"team": "Home"},
        "away_metrics": {"team": "Away"},
        "home_score": 28.0,
        "away_score": 21.0,
    }


def _meta(game_id="g1", season=2025):
    return {
        "game_id": game_id,
        "season": season,
        "venue_id": 999,
        "away_team_id": 10,
    }


def test_builds_bound_pre_fit_manifest_without_consuming_attempt():
    manifest, binding = _snapshot_manifest_and_binding()
    rows, report = build_altitude_dataset_manifest(
        baseline_rows=[_baseline()],
        game_metadata_rows=[_meta()],
        snapshot_records=_snapshot_records(),
        snapshot_manifest=manifest,
        frozen_snapshot_binding=binding,
    )
    assert rows[0]["altitude_delta_ft"] == 4280.0
    assert rows[0]["altitude_identity"] == {"game_venue_id": 999, "away_team_id": 10}
    assert report["status"] == "READY_FOR_ALTITUDE_CANDIDATE_EVALUATION"
    assert report["row_count"] == 1
    assert report["seasons"] == [2025]
    assert report["attempt_consumed"] is False
    assert report["attempts_used"] == 0
    assert report["fit_performed"] is False
    assert report["evaluation_performed"] is False
    assert report["model_p_created"] is False
    assert report["promotion_authority"] is False
    assert report["official_authority"] is False


def test_reconstructed_non_pit_baseline_is_rejected():
    manifest, binding = _snapshot_manifest_and_binding()
    row = _baseline()
    row["historical_pit_created"] = False
    row["provenance_class"] = "RECONSTRUCTED_HISTORICAL_NOT_PIT"
    with pytest.raises(CFBAltitudeDatasetError, match="BASELINE_NOT_PIT_ELIGIBLE:g1"):
        build_altitude_dataset_manifest(
            baseline_rows=[row],
            game_metadata_rows=[_meta()],
            snapshot_records=_snapshot_records(),
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )


def test_2026_is_prohibited_from_fit_tune_or_selection():
    manifest, binding = _snapshot_manifest_and_binding()
    with pytest.raises(CFBAltitudeDatasetError, match="2026_SELECTION_PROHIBITED:g1"):
        build_altitude_dataset_manifest(
            baseline_rows=[_baseline(season=2026)],
            game_metadata_rows=[_meta(season=2026)],
            snapshot_records=_snapshot_records(),
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )


def test_missing_altitude_metadata_fails_closed():
    manifest, binding = _snapshot_manifest_and_binding()
    meta = _meta()
    meta["venue_id"] = 12345
    with pytest.raises(CFBAltitudeDatasetError, match="GAME_VENUE_UNRESOLVED:12345"):
        build_altitude_dataset_manifest(
            baseline_rows=[_baseline()],
            game_metadata_rows=[meta],
            snapshot_records=_snapshot_records(),
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )


def test_game_identity_mismatch_fails_closed():
    manifest, binding = _snapshot_manifest_and_binding()
    with pytest.raises(CFBAltitudeDatasetError, match="GAME_METADATA_MISSING:g1"):
        build_altitude_dataset_manifest(
            baseline_rows=[_baseline()],
            game_metadata_rows=[_meta(game_id="g2")],
            snapshot_records=_snapshot_records(),
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )


def test_snapshot_rows_must_match_frozen_snapshot_hash():
    manifest, binding = _snapshot_manifest_and_binding()
    rows = _snapshot_records()
    rows[-1] = {**rows[-1], "elevation_ft": 123.0}
    with pytest.raises(CFBAltitudeDatasetError, match="SNAPSHOT_RECORDS_HASH_MISMATCH"):
        build_altitude_dataset_manifest(
            baseline_rows=[_baseline()],
            game_metadata_rows=[_meta()],
            snapshot_records=rows,
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )


def test_market_data_is_prohibited_from_altitude_selection_dataset():
    manifest, binding = _snapshot_manifest_and_binding()
    row = _baseline()
    row["spread_line"] = -3.5
    with pytest.raises(CFBAltitudeDatasetError, match="MARKET_DATA_PROHIBITED"):
        build_altitude_dataset_manifest(
            baseline_rows=[row],
            game_metadata_rows=[_meta()],
            snapshot_records=_snapshot_records(),
            snapshot_manifest=manifest,
            frozen_snapshot_binding=binding,
        )
