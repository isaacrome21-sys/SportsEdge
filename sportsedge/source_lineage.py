from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping

from .runtime import parse_timestamp


class SourceLineageError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalGameIdentity:
    mlb_game_pk: int
    scheduled_start_utc: str
    away_team_id: int
    home_team_id: int
    game_number: int | None
    sportsedge_game_id: str


@dataclass(frozen=True)
class SourceSnapshot:
    source_name: str
    source_record_id: str
    source_event_time: str
    fetched_at_utc: str
    sportsedge_game_id: str
    mlb_game_pk: int
    payload_sha256: str
    parser_version: str


@dataclass(frozen=True)
class FeatureLineage:
    feature_as_of_utc: str
    feature_contract_version: str
    feature_contract_sha256: str
    upstream_snapshot_hashes: tuple[str, ...]
    lineage_sha256: str


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise SourceLineageError(f"{field} must be timezone-aware ISO-8601") from exc
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise SourceLineageError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SourceLineageError(f"{field} must be a positive integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceLineageError(f"{field} must be a positive integer") from exc
    if out <= 0:
        raise SourceLineageError(f"{field} must be a positive integer")
    return out


def canonical_json_sha256(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SourceLineageError("payload is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def canonical_game_identity(*, mlb_game_pk: Any, scheduled_start: Any, away_team_id: Any, home_team_id: Any, game_number: Any = None) -> CanonicalGameIdentity:
    game_pk = _positive_int(mlb_game_pk, "mlb_game_pk")
    away_id = _positive_int(away_team_id, "away_team_id")
    home_id = _positive_int(home_team_id, "home_team_id")
    if away_id == home_id:
        raise SourceLineageError("away/home team identity collision")
    number = None if game_number is None else _positive_int(game_number, "game_number")
    start = _utc(scheduled_start, "scheduled_start")
    material = {
        "mlb_game_pk": game_pk,
        "scheduled_start_utc": start.isoformat(),
        "away_team_id": away_id,
        "home_team_id": home_id,
        "game_number": number,
    }
    sportsedge_game_id = f"MLB:{game_pk}:{canonical_json_sha256(material)[:16]}"
    return CanonicalGameIdentity(game_pk, start.isoformat(), away_id, home_id, number, sportsedge_game_id)


def build_source_snapshot(*, source_name: str, source_record_id: str, source_event_time: Any, fetched_at_utc: Any, game: CanonicalGameIdentity, payload: Any, parser_version: str) -> SourceSnapshot:
    if not source_name or not source_record_id or not parser_version:
        raise SourceLineageError("source_name/source_record_id/parser_version are required")
    event_time = _utc(source_event_time, "source_event_time")
    fetched_at = _utc(fetched_at_utc, "fetched_at_utc")
    if event_time > fetched_at:
        raise SourceLineageError("source_event_time cannot be after fetched_at_utc")
    return SourceSnapshot(
        source_name=str(source_name),
        source_record_id=str(source_record_id),
        source_event_time=event_time.isoformat(),
        fetched_at_utc=fetched_at.isoformat(),
        sportsedge_game_id=game.sportsedge_game_id,
        mlb_game_pk=game.mlb_game_pk,
        payload_sha256=canonical_json_sha256(payload),
        parser_version=str(parser_version),
    )


def build_feature_lineage(*, feature_as_of_utc: Any, scheduled_first_pitch: Any, feature_contract_version: str, feature_contract: Any, snapshots: Iterable[SourceSnapshot]) -> FeatureLineage:
    as_of = _utc(feature_as_of_utc, "feature_as_of_utc")
    first_pitch = _utc(scheduled_first_pitch, "scheduled_first_pitch")
    if as_of >= first_pitch:
        raise SourceLineageError("feature_as_of_utc must be before scheduled first pitch")
    snaps = tuple(snapshots)
    if not snaps:
        raise SourceLineageError("at least one source snapshot is required")
    game_ids = {s.sportsedge_game_id for s in snaps}
    game_pks = {s.mlb_game_pk for s in snaps}
    if len(game_ids) != 1 or len(game_pks) != 1:
        raise SourceLineageError("source snapshots cross game identity")
    for snap in snaps:
        event_time = _utc(snap.source_event_time, "source_event_time")
        fetched_at = _utc(snap.fetched_at_utc, "fetched_at_utc")
        if event_time > as_of or fetched_at > as_of:
            raise SourceLineageError("source snapshot was not available by feature_as_of_utc")
    contract_hash = canonical_json_sha256(feature_contract)
    snapshot_hashes = tuple(sorted(canonical_json_sha256(asdict(s)) for s in snaps))
    material = {
        "feature_as_of_utc": as_of.isoformat(),
        "feature_contract_version": feature_contract_version,
        "feature_contract_sha256": contract_hash,
        "upstream_snapshot_hashes": snapshot_hashes,
    }
    return FeatureLineage(
        feature_as_of_utc=as_of.isoformat(),
        feature_contract_version=str(feature_contract_version),
        feature_contract_sha256=contract_hash,
        upstream_snapshot_hashes=snapshot_hashes,
        lineage_sha256=canonical_json_sha256(material),
    )


def snapshot_to_dict(snapshot: SourceSnapshot) -> dict[str, Any]:
    return asdict(snapshot)
