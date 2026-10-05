"""Exact source receipt binding for NFL_SCORE_COUNTS_G1.

The caller acquires bytes. This module only verifies that every observed object
matches the frozen source contract before parsing/scoring and emits a
deterministic provenance manifest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_SOURCE_MANIFEST_V1"
CONTRACT_SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_SOURCE_CONTRACT_V1"
DEFAULT_CONTRACT = Path("config/research/nfl_score_counts_g1_source_contract_v1.json")
DEFAULT_SEASONS = tuple(range(2018, 2026))


class ScoreCountSourceError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


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


def load_source_contract(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_CONTRACT
    value = json.loads(p.read_text(encoding="utf-8"))
    if value.get("schema") != CONTRACT_SCHEMA:
        raise ScoreCountSourceError("SOURCE_CONTRACT_SCHEMA_INVALID")
    if value.get("status") != "FROZEN_BEFORE_ATTEMPT1_SOURCE_ACCESS":
        raise ScoreCountSourceError("SOURCE_CONTRACT_STATUS_INVALID")
    return value


def contract_payload_sha256(contract: Mapping[str, Any]) -> str:
    return sha256(_canonical(contract)).hexdigest()


def _expected(
    contract: Mapping[str, Any],
    seasons: Sequence[int],
) -> dict[str, dict[str, Any]]:
    values = tuple(int(s) for s in seasons)
    if not values or values != tuple(sorted(set(values))):
        raise ScoreCountSourceError("SEASONS_UNIQUE_SORTED_REQUIRED")
    expected: dict[str, dict[str, Any]] = {}
    sched = contract.get("schedule")
    if not isinstance(sched, Mapping):
        raise ScoreCountSourceError("SCHEDULE_CONTRACT_REQUIRED")
    expected["schedule"] = {
        "fetch_uri": str(sched["fetch_uri"]),
        "origin_uri": str(sched["fetch_uri"]),
        "season_scope": list(values),
        "expected_sha256": _sha(sched["expected_sha256"], "schedule.expected_sha256"),
    }
    pbp = contract.get("pbp")
    depth = contract.get("depth")
    if not isinstance(pbp, Mapping) or not isinstance(depth, Mapping):
        raise ScoreCountSourceError("SEASONAL_SOURCE_CONTRACT_REQUIRED")
    for season in values:
        for family, mapping in (("pbp", pbp), ("depth", depth)):
            spec = mapping.get(str(season))
            if not isinstance(spec, Mapping):
                raise ScoreCountSourceError(f"CONTRACT_SEASON_MISSING:{family}:{season}")
            expected[f"{family}_{season}"] = {
                "fetch_uri": str(spec["fetch_uri"]),
                "origin_uri": str(spec["origin_uri"]),
                "season_scope": [season],
                "expected_sha256": _sha(spec["expected_sha256"], f"{family}_{season}.expected_sha256"),
            }
    return expected


def build_score_count_source_manifest(
    receipts: Sequence[Mapping[str, Any]],
    *,
    parser_code_sha256: str,
    contract: Mapping[str, Any] | None = None,
    seasons: Sequence[int] = DEFAULT_SEASONS,
) -> dict[str, Any]:
    cfg = dict(contract or load_source_contract())
    if cfg.get("schema") != CONTRACT_SCHEMA:
        raise ScoreCountSourceError("SOURCE_CONTRACT_SCHEMA_INVALID")
    parser_sha = _sha(parser_code_sha256, "parser_code_sha256")
    expected = _expected(cfg, seasons)
    observed: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(receipts):
        if not isinstance(raw, Mapping):
            raise ScoreCountSourceError(f"receipt[{idx}]:OBJECT_REQUIRED")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ScoreCountSourceError(f"receipt[{idx}].name:REQUIRED")
        if name in observed:
            raise ScoreCountSourceError(f"SOURCE_NAME_DUPLICATE:{name}")
        spec = expected.get(name)
        if spec is None:
            raise ScoreCountSourceError(f"UNEXPECTED_SOURCE:{name}")
        fetch_uri = str(raw.get("fetch_uri") or raw.get("source_identifier") or "").strip()
        origin_uri = str(raw.get("origin_uri") or fetch_uri).strip()
        if fetch_uri != spec["fetch_uri"]:
            raise ScoreCountSourceError(f"FETCH_URI_MISMATCH:{name}")
        if origin_uri != spec["origin_uri"]:
            raise ScoreCountSourceError(f"ORIGIN_URI_MISMATCH:{name}")
        scope_raw = raw.get("season_scope")
        if not isinstance(scope_raw, (list, tuple)):
            raise ScoreCountSourceError(f"SEASON_SCOPE_REQUIRED:{name}")
        scope = [int(v) for v in scope_raw]
        if scope != spec["season_scope"]:
            raise ScoreCountSourceError(f"SEASON_SCOPE_MISMATCH:{name}")
        byte_sha = _sha(raw.get("byte_sha256") or raw.get("sha256"), f"{name}.byte_sha256")
        if byte_sha != spec["expected_sha256"]:
            raise ScoreCountSourceError(f"EXPECTED_SHA256_MISMATCH:{name}")
        receipt_parser = _sha(
            raw.get("parser_code_sha256") or parser_sha,
            f"{name}.parser_code_sha256",
        )
        if receipt_parser != parser_sha:
            raise ScoreCountSourceError(f"PARSER_IDENTITY_MISMATCH:{name}")
        observed[name] = {
            "name": name,
            "fetch_uri": fetch_uri,
            "origin_uri": origin_uri,
            "retrieved_at_utc": _utc(raw.get("retrieved_at_utc"), f"{name}.retrieved_at_utc"),
            "season_scope": scope,
            "byte_sha256": byte_sha,
            "parser_code_sha256": receipt_parser,
        }

    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ScoreCountSourceError("REQUIRED_SOURCE_MISSING:" + ",".join(missing))

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "EXACT_FROZEN_BYTES_VERIFIED_BEFORE_PARSE",
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "contract_payload_sha256": contract_payload_sha256(cfg),
        "parser_code_sha256": parser_sha,
        "seasons": [int(s) for s in seasons],
        "receipts": [observed[name] for name in sorted(observed)],
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "backfill": False,
        },
    }
    payload["manifest_sha256"] = sha256(_canonical(payload)).hexdigest()
    return payload


__all__ = [
    "CONTRACT_SCHEMA",
    "DEFAULT_CONTRACT",
    "DEFAULT_SEASONS",
    "SCHEMA",
    "ScoreCountSourceError",
    "build_score_count_source_manifest",
    "contract_payload_sha256",
    "load_source_contract",
]
