"""Source-manifest wrapper for NFL_SCORE_COUNTS_G1 development/forward evidence.

This extends the repository's canonical NFL byte manifest with the point-in-time
receipt fields frozen by the score-count preregistration: retrieval instant,
season scope, raw byte SHA-256 and parser-code SHA-256.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest, manifest_sha256

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_SOURCE_MANIFEST_V1"
SCHEDULE_SHA256 = "59c8bea7e185dde9e6053a06c24c34f6e5a91dcaea3187c0d9bab12759bb05fb"
SCHEDULE_URI = (
    "https://raw.githubusercontent.com/nflverse/nfldata/"
    "be9813d153e6694af4d98c7287a7db32225806ae/data/games.csv"
)
PBP_URI = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
DEPTH_URI = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "depth_charts/depth_charts_{season}.csv"
)
DEFAULT_SEASONS = tuple(range(2018, 2026))


class ScoreCountSourceError(ValueError):
    pass


def _sha(value: Any, field: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ScoreCountSourceError(f"{field}:SHA256_REQUIRED")
    return raw


def _utc(value: Any, field: str) -> str:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ScoreCountSourceError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ScoreCountSourceError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc).isoformat()


def _expected(seasons: Sequence[int]) -> dict[str, dict[str, Any]]:
    values = tuple(int(s) for s in seasons)
    if not values or values != tuple(sorted(set(values))):
        raise ScoreCountSourceError("SEASONS_UNIQUE_SORTED_REQUIRED")
    if any(s < 1900 or s > 2200 for s in values):
        raise ScoreCountSourceError("SEASON_OUT_OF_RANGE")
    expected: dict[str, dict[str, Any]] = {
        "schedule": {
            "uri": SCHEDULE_URI,
            "season_scope": list(values),
            "fixed_sha256": SCHEDULE_SHA256,
        }
    }
    for season in values:
        expected[f"pbp_{season}"] = {
            "uri": PBP_URI.format(season=season),
            "season_scope": [season],
            "fixed_sha256": None,
        }
        expected[f"depth_{season}"] = {
            "uri": DEPTH_URI.format(season=season),
            "season_scope": [season],
            "fixed_sha256": None,
        }
    return expected


def build_score_count_source_manifest(
    receipts: Sequence[Mapping[str, Any]],
    *,
    seasons: Sequence[int] = DEFAULT_SEASONS,
) -> dict[str, Any]:
    expected = _expected(seasons)
    observed: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(receipts):
        if not isinstance(raw, Mapping):
            raise ScoreCountSourceError(f"receipt[{idx}]:OBJECT_REQUIRED")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ScoreCountSourceError(f"receipt[{idx}].name:REQUIRED")
        if name in observed:
            raise ScoreCountSourceError(f"SOURCE_NAME_DUPLICATE:{name}")
        if name not in expected:
            raise ScoreCountSourceError(f"UNEXPECTED_SOURCE:{name}")
        spec = expected[name]
        uri = str(raw.get("source_identifier") or raw.get("uri") or "").strip()
        if uri != spec["uri"]:
            raise ScoreCountSourceError(f"SOURCE_IDENTIFIER_MISMATCH:{name}")
        raw_scope = raw.get("season_scope")
        if not isinstance(raw_scope, (list, tuple)):
            raise ScoreCountSourceError(f"SEASON_SCOPE_REQUIRED:{name}")
        scope = [int(v) for v in raw_scope]
        if scope != spec["season_scope"]:
            raise ScoreCountSourceError(f"SEASON_SCOPE_MISMATCH:{name}")
        byte_sha = _sha(raw.get("byte_sha256") or raw.get("sha256"), f"{name}.byte_sha256")
        parser_sha = _sha(raw.get("parser_code_sha256"), f"{name}.parser_code_sha256")
        if spec["fixed_sha256"] is not None and byte_sha != spec["fixed_sha256"]:
            raise ScoreCountSourceError(f"FIXED_SOURCE_SHA256_MISMATCH:{name}")
        observed[name] = {
            "name": name,
            "source_identifier": uri,
            "retrieved_at_utc": _utc(raw.get("retrieved_at_utc"), f"{name}.retrieved_at_utc"),
            "season_scope": scope,
            "byte_sha256": byte_sha,
            "parser_code_sha256": parser_sha,
        }

    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ScoreCountSourceError("REQUIRED_SOURCE_MISSING:" + ",".join(missing))

    detailed = [observed[name] for name in sorted(observed)]
    canonical = build_nfl_source_manifest(
        [
            {"name": row["name"], "uri": row["source_identifier"], "sha256": row["byte_sha256"]}
            for row in detailed
        ],
        schedule_anchor_sha256=SCHEDULE_SHA256,
    )
    canonical_hash = manifest_sha256(canonical)
    payload = {
        "schema": SCHEMA,
        "status": "BOUND_OBSERVED_BYTES_RESEARCH_ONLY",
        "seasons": [int(s) for s in seasons],
        "schedule_anchor_sha256": SCHEDULE_SHA256,
        "canonical_nfl_manifest": canonical,
        "canonical_nfl_manifest_sha256": canonical_hash,
        "receipts": detailed,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "backfill": False,
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["manifest_sha256"] = sha256(raw.encode("utf-8")).hexdigest()
    return payload


__all__ = [
    "DEFAULT_SEASONS",
    "DEPTH_URI",
    "PBP_URI",
    "SCHEMA",
    "SCHEDULE_SHA256",
    "SCHEDULE_URI",
    "ScoreCountSourceError",
    "build_score_count_source_manifest",
]
