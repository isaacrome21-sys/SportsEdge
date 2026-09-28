"""Deterministic materialization for the preregistered CFB altitude snapshot.

This module does not fit or score a model. It converts a pinned, public
CFBD-derived teams/venues export into the byte-stable JSONL snapshot required by
``CFB_ALTITUDE_CHALLENGER_POLICY_V1`` and emits a manifest that can be bound by
``verify_altitude_snapshot`` before any candidate evaluation.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha1, sha256
import io
import json
from typing import Any, Iterable, Mapping

from .altitude_prereg import EXPECTED_SOURCE_SCHEMA_COMMIT

SOURCE_PROVIDER = "CollegeFootballData"
SOURCE_MIRROR_REPOSITORY = "mslade50/football_weather"
SOURCE_MIRROR_COMMIT = "aea8274b8c2035372d19d8a509423b0645b7bfe9"
SOURCE_MIRROR_PATH = "data/raw/cfb_locations_updated.csv"
SOURCE_MIRROR_GIT_BLOB_SHA1 = "aa3ef7cfd7ea44b085508c8af46bbde72dd0da9c"
SOURCE_MIRROR_RAW_URL = (
    "https://raw.githubusercontent.com/"
    f"{SOURCE_MIRROR_REPOSITORY}/{SOURCE_MIRROR_COMMIT}/{SOURCE_MIRROR_PATH}"
)
METERS_TO_FEET = 3.280839895013123

_REQUIRED_COLUMNS = frozenset(
    {
        "Id",
        "School",
        "Classification",
        "Location Venue Id",
        "Location Name",
        "Location Elevation",
    }
)


class CFBAltitudeSnapshotError(ValueError):
    """Raised when the source cannot be transformed without inventing data."""


@dataclass(frozen=True)
class SnapshotMaterialization:
    snapshot_bytes: bytes
    manifest: Mapping[str, Any]


def git_blob_sha1(content: bytes) -> str:
    """Return the Git object id for raw blob bytes."""

    header = f"blob {len(content)}\0".encode("ascii")
    return sha1(header + content).hexdigest()


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise CFBAltitudeSnapshotError(f"ALTITUDE_SOURCE_INTEGER_INVALID:{text}") from exc


def _optional_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise CFBAltitudeSnapshotError(f"ALTITUDE_SOURCE_ELEVATION_INVALID:{text}") from exc
    if not (-2000.0 <= number <= 10000.0):
        raise CFBAltitudeSnapshotError(f"ALTITUDE_SOURCE_ELEVATION_OUT_OF_RANGE:{text}")
    return number


def _feet(meters: float | None) -> float | None:
    if meters is None:
        return None
    # Six decimals is far more precise than needed for the preregistered
    # thousand-foot feature while preserving deterministic bytes.
    return round(meters * METERS_TO_FEET, 6)


def _parse_rows(source_bytes: bytes) -> list[dict[str, str]]:
    try:
        text = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CFBAltitudeSnapshotError("ALTITUDE_SOURCE_UTF8_REQUIRED") from exc
    reader = csv.DictReader(io.StringIO(text))
    fields = frozenset(reader.fieldnames or ())
    missing = sorted(_REQUIRED_COLUMNS - fields)
    if missing:
        raise CFBAltitudeSnapshotError(
            "ALTITUDE_SOURCE_COLUMNS_MISSING:" + ",".join(missing)
        )
    return [dict(row) for row in reader]


def build_snapshot_records(source_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build canonical team + home-venue records from the pinned CFBD export.

    Null elevation is preserved as null. It is never imputed. If the same
    venue id appears with two distinct non-null CFBD elevations, materialization
    fails instead of averaging or choosing one after looking at outcomes.
    """

    rows = _parse_rows(source_bytes)
    teams: list[dict[str, Any]] = []
    venues: dict[int, dict[str, Any]] = {}
    teams_missing_elevation = 0
    teams_missing_venue = 0

    for row in rows:
        team_id = _optional_int(row.get("Id"))
        if team_id is None:
            raise CFBAltitudeSnapshotError("ALTITUDE_SOURCE_TEAM_ID_MISSING")
        venue_id = _optional_int(row.get("Location Venue Id"))
        elevation_m = _optional_float(row.get("Location Elevation"))
        elevation_ft = _feet(elevation_m)
        if venue_id is None:
            teams_missing_venue += 1
        if elevation_m is None:
            teams_missing_elevation += 1

        teams.append(
            {
                "entity_type": "team",
                "id": team_id,
                "school": str(row.get("School") or "").strip(),
                "classification": str(row.get("Classification") or "").strip().lower() or None,
                "location": {
                    "id": venue_id,
                    "name": str(row.get("Location Name") or "").strip() or None,
                    "elevation_m": elevation_m,
                    "elevation_ft": elevation_ft,
                },
            }
        )

        if venue_id is None:
            continue
        existing = venues.get(venue_id)
        if existing is None:
            venues[venue_id] = {
                "entity_type": "venue",
                "id": venue_id,
                "name": str(row.get("Location Name") or "").strip() or None,
                "elevation_m": elevation_m,
                "elevation_ft": elevation_ft,
            }
            continue

        previous = existing.get("elevation_m")
        if previous is not None and elevation_m is not None and abs(float(previous) - elevation_m) > 1e-9:
            raise CFBAltitudeSnapshotError(
                f"ALTITUDE_SOURCE_VENUE_ELEVATION_CONFLICT:{venue_id}:{previous}:{elevation_m}"
            )
        if previous is None and elevation_m is not None:
            # This is not imputation: the same CFBD venue is present on another
            # source row with an explicit value. Preserve that source value on
            # the venue entity while the team row above remains null.
            existing["elevation_m"] = elevation_m
            existing["elevation_ft"] = elevation_ft
        if not existing.get("name") and str(row.get("Location Name") or "").strip():
            existing["name"] = str(row["Location Name"]).strip()

    records = sorted([*teams, *venues.values()], key=lambda r: (str(r["entity_type"]), int(r["id"])))
    venue_missing_elevation = sum(1 for row in venues.values() if row.get("elevation_m") is None)
    stats = {
        "source_rows": len(rows),
        "team_records": len(teams),
        "venue_records": len(venues),
        "teams_missing_venue": teams_missing_venue,
        "teams_missing_elevation": teams_missing_elevation,
        "venues_missing_elevation": venue_missing_elevation,
    }
    return records, stats


def canonical_jsonl(records: Iterable[Mapping[str, Any]]) -> bytes:
    lines = [json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=False) for row in records]
    if not lines:
        raise CFBAltitudeSnapshotError("ALTITUDE_SNAPSHOT_EMPTY")
    return ("\n".join(lines) + "\n").encode("utf-8")


def materialize_snapshot(
    source_bytes: bytes,
    *,
    retrieved_at_utc: str,
    expected_git_blob_sha1: str = SOURCE_MIRROR_GIT_BLOB_SHA1,
) -> SnapshotMaterialization:
    """Verify source bytes, build deterministic JSONL, and return its manifest."""

    actual_blob = git_blob_sha1(source_bytes)
    if actual_blob != expected_git_blob_sha1:
        raise CFBAltitudeSnapshotError(
            f"ALTITUDE_SOURCE_GIT_BLOB_MISMATCH:expected={expected_git_blob_sha1}:actual={actual_blob}"
        )
    if not str(retrieved_at_utc).strip():
        raise CFBAltitudeSnapshotError("ALTITUDE_RETRIEVED_AT_REQUIRED")

    records, stats = build_snapshot_records(source_bytes)
    snapshot_bytes = canonical_jsonl(records)
    manifest: dict[str, Any] = {
        # Required by CFB_ALTITUDE_CHALLENGER_POLICY_V1.
        "source_provider": SOURCE_PROVIDER,
        "source_schema_commit_sha": EXPECTED_SOURCE_SCHEMA_COMMIT,
        "retrieved_at_utc": str(retrieved_at_utc),
        "record_count": len(records),
        "content_sha256": sha256(snapshot_bytes).hexdigest(),
        # Extra immutable provenance for the free public retrieval mirror.
        "source_mirror_repository": SOURCE_MIRROR_REPOSITORY,
        "source_mirror_commit_sha": SOURCE_MIRROR_COMMIT,
        "source_mirror_path": SOURCE_MIRROR_PATH,
        "source_mirror_git_blob_sha1": actual_blob,
        "source_content_sha256": sha256(source_bytes).hexdigest(),
        "source_elevation_units": "meters",
        "derived_elevation_units": "feet",
        "meters_to_feet": METERS_TO_FEET,
        "missing_elevation_policy": "PRESERVE_NULL_FAIL_CLOSED_NO_IMPUTATION",
        "stats": stats,
        "governance": {
            "fit_performed": False,
            "evaluation_performed": False,
            "attempt_consumed": False,
            "model_p_created": False,
            "promotion_authority": False,
            "official_authority": False,
        },
    }
    return SnapshotMaterialization(snapshot_bytes=snapshot_bytes, manifest=manifest)


def verify_frozen_binding(*, manifest: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless a regenerated snapshot exactly matches the frozen proof."""

    expected_pairs = {
        "source_provider": binding.get("source_provider"),
        "source_schema_commit_sha": binding.get("source_schema_commit_sha"),
        "source_mirror_repository": binding.get("source_mirror_repository"),
        "source_mirror_commit_sha": binding.get("source_mirror_commit_sha"),
        "source_mirror_path": binding.get("source_mirror_path"),
        "source_mirror_git_blob_sha1": binding.get("source_mirror_git_blob_sha1"),
        "source_content_sha256": binding.get("source_content_sha256"),
        "content_sha256": binding.get("snapshot_content_sha256"),
        "record_count": binding.get("snapshot_record_count"),
    }
    for manifest_key, expected in expected_pairs.items():
        actual = manifest.get(manifest_key)
        if expected is None:
            raise CFBAltitudeSnapshotError(f"ALTITUDE_BINDING_FIELD_MISSING:{manifest_key}")
        if actual != expected:
            raise CFBAltitudeSnapshotError(
                f"ALTITUDE_BINDING_MISMATCH:{manifest_key}:expected={expected}:actual={actual}"
            )

    manifest_stats = manifest.get("stats")
    if not isinstance(manifest_stats, Mapping):
        raise CFBAltitudeSnapshotError("ALTITUDE_BINDING_MANIFEST_STATS_MISSING")
    for key in (
        "source_rows",
        "team_records",
        "venue_records",
        "teams_missing_venue",
        "teams_missing_elevation",
        "venues_missing_elevation",
    ):
        expected = binding.get(key)
        if expected is None:
            raise CFBAltitudeSnapshotError(f"ALTITUDE_BINDING_FIELD_MISSING:{key}")
        actual = manifest_stats.get(key)
        if actual != expected:
            raise CFBAltitudeSnapshotError(
                f"ALTITUDE_BINDING_MISMATCH:stats.{key}:expected={expected}:actual={actual}"
            )

    governance = binding.get("governance")
    if not isinstance(governance, Mapping):
        raise CFBAltitudeSnapshotError("ALTITUDE_BINDING_GOVERNANCE_MISSING")
    if governance.get("attempts_used") != 0 or governance.get("attempts_max") != 3:
        raise CFBAltitudeSnapshotError("ALTITUDE_BINDING_ATTEMPT_STATE_INVALID")
    for key in (
        "fit_performed",
        "evaluation_performed",
        "attempt_consumed",
        "model_p_created",
        "truth_gate_authority",
        "promotion_authority",
        "official_authority",
    ):
        if governance.get(key) is not False:
            raise CFBAltitudeSnapshotError(f"ALTITUDE_BINDING_GOVERNANCE_NOT_FALSE:{key}")

    return {
        "status": "FROZEN_STATIC_SOURCE_BINDING_VERIFIED_NO_EVALUATION",
        "content_sha256": manifest["content_sha256"],
        "record_count": manifest["record_count"],
        "attempts_used": 0,
        "attempts_max": 3,
        "fit_performed": False,
        "evaluation_performed": False,
    }


__all__ = [
    "CFBAltitudeSnapshotError",
    "METERS_TO_FEET",
    "SOURCE_MIRROR_COMMIT",
    "SOURCE_MIRROR_GIT_BLOB_SHA1",
    "SOURCE_MIRROR_PATH",
    "SOURCE_MIRROR_RAW_URL",
    "SOURCE_MIRROR_REPOSITORY",
    "SnapshotMaterialization",
    "build_snapshot_records",
    "canonical_jsonl",
    "git_blob_sha1",
    "materialize_snapshot",
    "verify_frozen_binding",
]
