"""Dataset binding for the preregistered CFB altitude challenger.

This is a pre-fit gate only. It binds PIT-eligible baseline rows, game identity
metadata, and the frozen altitude snapshot into one deterministic manifest. It never
fits/scores a model and never consumes an altitude challenger attempt.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .altitude_features import CFBAltitudeFeatureError, altitude_delta_ft
from .altitude_snapshot import verify_frozen_binding


class CFBAltitudeDatasetError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _game_id(row: Mapping[str, Any], *, source: str) -> str:
    gid = str(row.get("game_id") or "").strip()
    if not gid:
        raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_GAME_ID_MISSING:{source}")
    return gid


def _season(row: Mapping[str, Any], *, game_id: str) -> int:
    try:
        season = int(row.get("season"))
    except (TypeError, ValueError) as exc:
        raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_SEASON_INVALID:{game_id}") from exc
    if season == 2026:
        raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_2026_SELECTION_PROHIBITED:{game_id}")
    if season < 2000 or season > 2100:
        raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_SEASON_INVALID:{game_id}")
    return season


def _require_pit_baseline(row: Mapping[str, Any], *, game_id: str) -> None:
    """Fail closed unless the baseline row is explicitly pre-event/PIT eligible."""
    if row.get("historical_pit_created") is True:
        return
    provenance = str(row.get("provenance_class") or "").strip().upper()
    if provenance == "PRE_EVENT_ARCHIVE":
        return
    raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_BASELINE_NOT_PIT_ELIGIBLE:{game_id}")


def _snapshot_indexes(snapshot_records: Sequence[Mapping[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    teams: dict[int, dict[str, Any]] = {}
    venues: dict[int, dict[str, Any]] = {}
    for raw in snapshot_records:
        row = dict(raw)
        entity = str(row.get("entity_type") or "").strip().lower()
        try:
            entity_id = int(row.get("id"))
        except (TypeError, ValueError) as exc:
            raise CFBAltitudeDatasetError("ALTITUDE_DATASET_ENTITY_ID_INVALID") from exc
        if entity_id <= 0:
            raise CFBAltitudeDatasetError("ALTITUDE_DATASET_ENTITY_ID_INVALID")
        target = teams if entity == "team" else venues if entity == "venue" else None
        if target is None:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_ENTITY_TYPE_INVALID:{entity or 'MISSING'}")
        if entity_id in target:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_ENTITY_DUPLICATE:{entity}:{entity_id}")
        target[entity_id] = row
    if not teams or not venues:
        raise CFBAltitudeDatasetError("ALTITUDE_DATASET_SNAPSHOT_INCOMPLETE")
    return teams, venues


def build_altitude_dataset_manifest(
    *,
    baseline_rows: Sequence[Mapping[str, Any]],
    game_metadata_rows: Sequence[Mapping[str, Any]],
    snapshot_records: Sequence[Mapping[str, Any]],
    snapshot_manifest: Mapping[str, Any],
    frozen_snapshot_binding: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bind an evaluation dataset without fitting or looking at candidate scores.

    Required game metadata fields are game_id, season, venue_id, and away_team_id.
    The venue_id is the actual target-game venue, including neutral-site games.
    """
    if not baseline_rows:
        raise CFBAltitudeDatasetError("ALTITUDE_DATASET_BASELINE_ROWS_EMPTY")
    if not game_metadata_rows:
        raise CFBAltitudeDatasetError("ALTITUDE_DATASET_GAME_METADATA_EMPTY")

    frozen = verify_frozen_binding(manifest=snapshot_manifest, binding=frozen_snapshot_binding)
    if frozen.get("status") != "FROZEN_STATIC_SOURCE_BINDING_VERIFIED_NO_EVALUATION":
        raise CFBAltitudeDatasetError("ALTITUDE_DATASET_SNAPSHOT_BINDING_NOT_VERIFIED")

    teams, venues = _snapshot_indexes(snapshot_records)
    metadata: dict[str, dict[str, Any]] = {}
    for raw in game_metadata_rows:
        row = dict(raw)
        gid = _game_id(row, source="GAME_METADATA")
        if gid in metadata:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_GAME_METADATA_DUPLICATE:{gid}")
        _season(row, game_id=gid)
        metadata[gid] = row

    enriched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in baseline_rows:
        row = dict(raw)
        gid = _game_id(row, source="BASELINE")
        if gid in seen:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_BASELINE_DUPLICATE:{gid}")
        seen.add(gid)
        season = _season(row, game_id=gid)
        _require_pit_baseline(row, game_id=gid)

        meta = metadata.get(gid)
        if meta is None:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_GAME_METADATA_MISSING:{gid}")
        if _season(meta, game_id=gid) != season:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_SEASON_MISMATCH:{gid}")

        try:
            delta = altitude_delta_ft(
                teams=teams,
                venues=venues,
                game_venue_id=meta.get("venue_id"),
                away_team_id=meta.get("away_team_id"),
            )
        except CFBAltitudeFeatureError as exc:
            raise CFBAltitudeDatasetError(f"ALTITUDE_DATASET_FEATURE_BLOCKED:{gid}:{exc}") from exc

        enriched.append({
            **row,
            "altitude_identity": {
                "game_venue_id": int(meta["venue_id"]),
                "away_team_id": int(meta["away_team_id"]),
            },
            "altitude_delta_ft": delta,
        })

    extra_metadata = sorted(set(metadata) - seen)
    if extra_metadata:
        raise CFBAltitudeDatasetError("ALTITUDE_DATASET_UNMATCHED_GAME_METADATA:" + ",".join(extra_metadata[:10]))

    enriched.sort(key=lambda row: (int(row["season"]), int(row.get("week", 0)), str(row["game_id"])))
    seasons = sorted({int(row["season"]) for row in enriched})

    manifest = {
        "schema": "CFB_ALTITUDE_DATASET_MANIFEST_V1",
        "status": "READY_FOR_ALTITUDE_CANDIDATE_EVALUATION",
        "row_count": len(enriched),
        "seasons": seasons,
        "baseline_rows_sha256": _canonical_sha256([dict(row) for row in baseline_rows]),
        "game_metadata_sha256": _canonical_sha256([dict(row) for row in game_metadata_rows]),
        "altitude_snapshot_sha256": str(snapshot_manifest.get("content_sha256") or ""),
        "enriched_rows_sha256": _canonical_sha256(enriched),
        "pit_baseline_required": True,
        "season_2026_used_for_fit_tune_or_selection": False,
        "market_data_used": False,
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed": False,
        "attempts_used": 0,
        "attempts_max": 3,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }
    return enriched, manifest


__all__ = ["CFBAltitudeDatasetError", "build_altitude_dataset_manifest"]
