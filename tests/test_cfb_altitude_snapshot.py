from __future__ import annotations

import json
from pathlib import Path

import pytest

from sportsedge.sports.cfb.altitude_prereg import POLICY_PATH, verify_altitude_snapshot
from sportsedge.sports.cfb.altitude_snapshot import (
    CFBAltitudeSnapshotError,
    git_blob_sha1,
    materialize_snapshot,
    verify_frozen_binding,
)


HEADER = (
    "Id,School,Classification,Location Venue Id,Location Name,Location Elevation\n"
)


def _source(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode("utf-8")


def _binding_for(manifest: dict[str, object]) -> dict[str, object]:
    stats = dict(manifest["stats"])  # type: ignore[arg-type]
    return {
        "source_provider": manifest["source_provider"],
        "source_schema_commit_sha": manifest["source_schema_commit_sha"],
        "source_mirror_repository": manifest["source_mirror_repository"],
        "source_mirror_commit_sha": manifest["source_mirror_commit_sha"],
        "source_mirror_path": manifest["source_mirror_path"],
        "source_mirror_git_blob_sha1": manifest["source_mirror_git_blob_sha1"],
        "source_content_sha256": manifest["source_content_sha256"],
        "snapshot_content_sha256": manifest["content_sha256"],
        "snapshot_record_count": manifest["record_count"],
        **stats,
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


def test_snapshot_is_deterministic_sorted_and_converts_meters_to_feet() -> None:
    raw = _source(
        "2006,Akron,fbs,3768,InfoCision Stadium,321.2875061",
        "333,Alabama,fbs,3657,Bryant Denny Stadium,70.05136108",
    )
    expected_blob = git_blob_sha1(raw)
    a = materialize_snapshot(
        raw,
        retrieved_at_utc="2026-09-28T01:00:00Z",
        expected_git_blob_sha1=expected_blob,
    )
    b = materialize_snapshot(
        raw,
        retrieved_at_utc="2026-09-28T01:00:00Z",
        expected_git_blob_sha1=expected_blob,
    )
    assert a.snapshot_bytes == b.snapshot_bytes
    lines = [json.loads(x) for x in a.snapshot_bytes.decode().splitlines()]
    assert [(row["entity_type"], row["id"]) for row in lines] == [
        ("team", 333),
        ("team", 2006),
        ("venue", 3657),
        ("venue", 3768),
    ]
    alabama = lines[0]
    assert alabama["location"]["elevation_m"] == 70.05136108
    # 70.05136108 m * exact meters-to-feet constant = 229.827300... ft.
    assert alabama["location"]["elevation_ft"] == pytest.approx(229.8273, abs=1e-6)
    assert a.manifest["governance"]["attempt_consumed"] is False
    assert a.manifest["governance"]["evaluation_performed"] is False


def test_missing_elevation_is_preserved_null_not_imputed() -> None:
    raw = _source("2001,Adams State,ii,5866,Rex Stadium,")
    materialized = materialize_snapshot(
        raw,
        retrieved_at_utc="2026-09-28T01:00:00Z",
        expected_git_blob_sha1=git_blob_sha1(raw),
    )
    rows = [json.loads(x) for x in materialized.snapshot_bytes.decode().splitlines()]
    team = next(row for row in rows if row["entity_type"] == "team")
    venue = next(row for row in rows if row["entity_type"] == "venue")
    assert team["location"]["elevation_m"] is None
    assert venue["elevation_m"] is None
    assert materialized.manifest["stats"]["teams_missing_elevation"] == 1
    assert materialized.manifest["stats"]["venues_missing_elevation"] == 1


def test_conflicting_duplicate_venue_elevation_fails_closed() -> None:
    raw = _source(
        "1,One,fbs,50,Shared,100.0",
        "2,Two,fbs,50,Shared,101.0",
    )
    with pytest.raises(CFBAltitudeSnapshotError, match="VENUE_ELEVATION_CONFLICT"):
        materialize_snapshot(
            raw,
            retrieved_at_utc="2026-09-28T01:00:00Z",
            expected_git_blob_sha1=git_blob_sha1(raw),
        )


def test_unpinned_source_bytes_fail_closed() -> None:
    raw = _source("333,Alabama,fbs,3657,Bryant Denny Stadium,70.0")
    with pytest.raises(CFBAltitudeSnapshotError, match="GIT_BLOB_MISMATCH"):
        materialize_snapshot(
            raw,
            retrieved_at_utc="2026-09-28T01:00:00Z",
            expected_git_blob_sha1="0" * 40,
        )


def test_materialized_manifest_binds_existing_frozen_policy(tmp_path: Path) -> None:
    raw = _source("333,Alabama,fbs,3657,Bryant Denny Stadium,70.0")
    materialized = materialize_snapshot(
        raw,
        retrieved_at_utc="2026-09-28T01:00:00Z",
        expected_git_blob_sha1=git_blob_sha1(raw),
    )
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_bytes(materialized.snapshot_bytes)
    policy = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
    result = verify_altitude_snapshot(
        policy=policy,
        manifest=materialized.manifest,
        snapshot_path=snapshot,
    )
    assert result["status"] == "SNAPSHOT_BOUND_NO_EVALUATION"
    assert result["attempt_consumed_by_this_verifier"] is False


def test_frozen_binding_accepts_exact_regeneration_and_rejects_drift() -> None:
    raw = _source("333,Alabama,fbs,3657,Bryant Denny Stadium,70.0")
    materialized = materialize_snapshot(
        raw,
        retrieved_at_utc="2026-09-28T01:00:00Z",
        expected_git_blob_sha1=git_blob_sha1(raw),
    )
    manifest = dict(materialized.manifest)
    binding = _binding_for(manifest)
    result = verify_frozen_binding(manifest=manifest, binding=binding)
    assert result["status"] == "FROZEN_STATIC_SOURCE_BINDING_VERIFIED_NO_EVALUATION"
    assert result["attempts_used"] == 0

    binding["snapshot_content_sha256"] = "0" * 64
    with pytest.raises(CFBAltitudeSnapshotError, match="ALTITUDE_BINDING_MISMATCH:content_sha256"):
        verify_frozen_binding(manifest=manifest, binding=binding)
