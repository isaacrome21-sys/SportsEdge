"""PIT-safe source projection and provenance for NFL score-count forward serving."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_SOURCE_MANIFEST_V1"
_EASTERN = ZoneInfo("America/New_York")

SCHEDULE_FIELDS = (
    "game_id",
    "season",
    "week",
    "game_type",
    "gameday",
    "gametime",
    "start_time",
    "home_team",
    "away_team",
)
DEPTH_FIELDS = (
    "dt",
    "season",
    "week",
    "game_type",
    "team",
    "club_code",
    "pos_abb",
    "position",
    "depth_position",
    "pos_rank",
    "depth_team",
    "gsis_id",
)


class ScoreCountForwardSourceError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ScoreCountForwardSourceError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ScoreCountForwardSourceError(f"{field}:TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def project_schedule_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ScoreCountForwardSourceError("SCHEDULE_ROW_OBJECT_REQUIRED")
        out.append({field: raw.get(field) for field in SCHEDULE_FIELDS if field in raw})
    return out


def project_depth_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ScoreCountForwardSourceError("DEPTH_ROW_OBJECT_REQUIRED")
        out.append({field: raw.get(field) for field in DEPTH_FIELDS if field in raw})
    return out


def _schedule_start(row: Mapping[str, Any]) -> datetime:
    raw = row.get("start_time")
    if raw not in (None, ""):
        return _utc(raw, "start_time")
    day = str(row.get("gameday") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        raise ScoreCountForwardSourceError("SCHEDULE_START_REQUIRED")
    try:
        local = datetime.combine(
            date.fromisoformat(day[:10]),
            time.fromisoformat(clock),
            tzinfo=_EASTERN,
        )
    except ValueError as exc:
        raise ScoreCountForwardSourceError("SCHEDULE_START_INVALID") from exc
    return local.astimezone(timezone.utc)


def select_forward_targets(
    schedule_rows: Sequence[Mapping[str, Any]],
    *,
    as_of: Any,
    horizon_days: int = 7,
    season: int = 2026,
    minimum_week: int = 5,
    explicit_game_ids: Sequence[str] = (),
) -> list[str]:
    stamp = _utc(as_of, "as_of")
    try:
        horizon = int(horizon_days)
    except (TypeError, ValueError) as exc:
        raise ScoreCountForwardSourceError("HORIZON_DAYS_INTEGER_REQUIRED") from exc
    if horizon < 1:
        raise ScoreCountForwardSourceError("HORIZON_DAYS_POSITIVE_REQUIRED")
    explicit = {str(x).strip() for x in explicit_game_ids if str(x).strip()}
    end = stamp + timedelta(days=horizon)
    eligible: dict[str, datetime] = {}
    for row in schedule_rows:
        try:
            row_season = int(float(row.get("season")))
            row_week = int(float(row.get("week")))
        except (TypeError, ValueError):
            continue
        if row_season != int(season) or row_week < int(minimum_week):
            continue
        if str(row.get("game_type") or "REG").strip().upper() not in {"REG", "POST"}:
            continue
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            continue
        start = _schedule_start(row)
        if stamp < start <= end:
            eligible[gid] = start

    if explicit:
        missing = sorted(explicit - set(eligible))
        if missing:
            raise ScoreCountForwardSourceError(
                "EXPLICIT_TARGET_NOT_ELIGIBLE:" + ",".join(missing)
            )
        return sorted(explicit, key=lambda gid: (eligible[gid], gid))
    return sorted(eligible, key=lambda gid: (eligible[gid], gid))


def build_forward_source_manifest(
    receipts: Sequence[Mapping[str, Any]],
    *,
    prediction_at: Any,
    target_game_ids: Sequence[str],
    fit_artifact_sha256: str,
    fit_training_source_manifest_sha256: str,
    serving_code_identity: str,
) -> dict[str, Any]:
    stamp = _utc(prediction_at, "prediction_at")
    targets = [str(x).strip() for x in target_game_ids if str(x).strip()]
    if not targets:
        raise ScoreCountForwardSourceError("TARGET_GAME_IDS_REQUIRED")
    normalized = []
    for idx, raw in enumerate(receipts):
        if not isinstance(raw, Mapping):
            raise ScoreCountForwardSourceError(f"receipt[{idx}]:OBJECT_REQUIRED")
        retrieved = _utc(
            raw.get("retrieved_at_utc"), f"receipt[{idx}].retrieved_at_utc"
        )
        if not retrieved < stamp:
            raise ScoreCountForwardSourceError(
                f"receipt[{idx}]:SOURCE_NOT_PREGAME"
            )
        item = {
            "name": str(raw.get("name") or "").strip(),
            "source_uri": str(raw.get("source_uri") or "").strip(),
            "retrieved_at_utc": retrieved.isoformat(),
            "byte_sha256": str(raw.get("byte_sha256") or "").strip().lower(),
            "immutable_expected_sha256": (
                str(raw.get("immutable_expected_sha256")).strip().lower()
                if raw.get("immutable_expected_sha256") not in (None, "")
                else None
            ),
            "season_scope": [int(x) for x in (raw.get("season_scope") or [])],
        }
        if not item["name"] or not item["source_uri"]:
            raise ScoreCountForwardSourceError(f"receipt[{idx}]:IDENTITY_REQUIRED")
        for field in ("byte_sha256",):
            value = str(item[field])
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ScoreCountForwardSourceError(f"receipt[{idx}].{field}:SHA256_REQUIRED")
        expected = item["immutable_expected_sha256"]
        if expected is not None:
            if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
                raise ScoreCountForwardSourceError(
                    f"receipt[{idx}].immutable_expected_sha256:SHA256_REQUIRED"
                )
            if expected != item["byte_sha256"]:
                raise ScoreCountForwardSourceError(
                    f"receipt[{idx}]:IMMUTABLE_SOURCE_SHA_MISMATCH"
                )
        normalized.append(item)

    fit_sha = str(fit_artifact_sha256 or "").strip().lower()
    training_sha = str(fit_training_source_manifest_sha256 or "").strip().lower()
    for value, field in (
        (fit_sha, "fit_artifact_sha256"),
        (training_sha, "fit_training_source_manifest_sha256"),
    ):
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ScoreCountForwardSourceError(f"{field}:SHA256_REQUIRED")
    code = str(serving_code_identity or "").strip().lower()
    if len(code) != 64 or any(ch not in "0123456789abcdef" for ch in code):
        raise ScoreCountForwardSourceError("SERVING_CODE_IDENTITY_SHA256_REQUIRED")
    for item in normalized:
        item["parser_code_sha256"] = code

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "prediction_at": stamp.isoformat(),
        "target_game_ids": targets,
        "fit_artifact_sha256": fit_sha,
        "fit_training_source_manifest_sha256": training_sha,
        "serving_code_identity": code,
        "schedule_projection_fields": list(SCHEDULE_FIELDS),
        "depth_projection_fields": list(DEPTH_FIELDS),
        "pbp_projection": "score_counts_source_projection.project_pbp_row",
        "market_columns_projected_out_before_feature_builder": True,
        "target_game_pbp_forbidden": True,
        "receipts": sorted(normalized, key=lambda row: row["name"]),
        "authority": {
            "research_only": True,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "backfill": False,
        },
    }
    payload["manifest_sha256"] = _digest(payload)
    return payload


__all__ = [
    "DEPTH_FIELDS",
    "SCHEDULE_FIELDS",
    "SCHEMA",
    "ScoreCountForwardSourceError",
    "build_forward_source_manifest",
    "project_depth_rows",
    "project_schedule_rows",
    "select_forward_targets",
]
