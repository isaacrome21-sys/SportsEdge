"""Forward provenance for NFL_SCORE_COUNTS_G1."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

RECEIPT_SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_SOURCE_RECEIPTS_V1"


class ScoreCountForwardError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ScoreCountForwardError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ScoreCountForwardError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_forward_receipts(
    payload: Mapping[str, Any], *, prediction_at: Any, parser_code_sha256: str
) -> dict[str, Any]:
    if payload.get("schema") != RECEIPT_SCHEMA:
        raise ScoreCountForwardError("FORWARD_RECEIPT_SCHEMA_INVALID")
    stamp = _utc(prediction_at, "prediction_at")
    sources = payload.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)) or not sources:
        raise ScoreCountForwardError("FORWARD_SOURCES_REQUIRED")
    parser = str(parser_code_sha256).lower()
    if len(parser) != 64:
        raise ScoreCountForwardError("PARSER_SHA256_REQUIRED")
    out = []
    names = set()
    roles = {"schedule": 0, "pbp": 0, "depth": 0}
    coverage = {"pbp": set(), "depth": set()}
    for raw in sources:
        if not isinstance(raw, Mapping):
            raise ScoreCountForwardError("FORWARD_SOURCE_OBJECT_REQUIRED")
        name = str(raw.get("name") or "").strip()
        role = str(raw.get("role") or "").lower().strip()
        if not name or name in names or role not in roles:
            raise ScoreCountForwardError("FORWARD_SOURCE_IDENTITY_INVALID")
        names.add(name)
        roles[role] += 1
        path = Path(str(raw.get("path") or ""))
        if not path.is_file():
            raise ScoreCountForwardError(f"FORWARD_SOURCE_FILE_MISSING:{name}")
        retrieved = _utc(raw.get("retrieved_at_utc"), f"{name}.retrieved_at_utc")
        if retrieved >= stamp:
            raise ScoreCountForwardError(f"FORWARD_SOURCE_NOT_PREGAME:{name}")
        expected = str(raw.get("byte_sha256") or "").lower()
        if len(expected) != 64 or _sha_file(path) != expected:
            raise ScoreCountForwardError(f"FORWARD_SOURCE_SHA_MISMATCH:{name}")
        receipt_parser = str(raw.get("parser_code_sha256") or parser).lower()
        if receipt_parser != parser:
            raise ScoreCountForwardError(f"FORWARD_SOURCE_PARSER_MISMATCH:{name}")
        source_identifier = str(raw.get("source_identifier") or "").strip()
        if not source_identifier:
            raise ScoreCountForwardError(f"FORWARD_SOURCE_IDENTIFIER_REQUIRED:{name}")
        scope_raw = raw.get("season_scope")
        if not isinstance(scope_raw, Sequence) or isinstance(scope_raw, (str, bytes)):
            raise ScoreCountForwardError(f"FORWARD_SOURCE_SEASON_SCOPE_REQUIRED:{name}")
        scope = [int(v) for v in scope_raw]
        if not scope or scope != sorted(set(scope)):
            raise ScoreCountForwardError(f"FORWARD_SOURCE_SEASON_SCOPE_INVALID:{name}")
        if role in coverage:
            overlap = coverage[role].intersection(scope)
            if overlap:
                raise ScoreCountForwardError(f"FORWARD_SOURCE_SEASON_OVERLAP:{role}")
            coverage[role].update(scope)
        out.append({
            "name": name,
            "role": role,
            "source_identifier": source_identifier,
            "retrieved_at_utc": retrieved.isoformat(),
            "season_scope": scope,
            "byte_sha256": expected,
            "parser_code_sha256": parser,
        })
    if roles["schedule"] != 1 or not roles["pbp"] or not roles["depth"]:
        raise ScoreCountForwardError("FORWARD_SOURCE_ROLES_INCOMPLETE")
    required = set(range(2018, 2027))
    for role in ("pbp", "depth"):
        if coverage[role] != required:
            raise ScoreCountForwardError(f"FORWARD_SOURCE_SEASON_COVERAGE_REQUIRED:{role}")
    core = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_SOURCE_MANIFEST_V1",
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "prediction_at": stamp.isoformat(),
        "parser_code_sha256": parser,
        "sources": sorted(out, key=lambda x: x["name"]),
        "market_data_used": False,
    }
    core["manifest_sha256"] = sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return core


def build_forward_bundle(
    *, fit_artifact: Mapping[str, Any], prediction: Mapping[str, Any],
    forward_manifest: Mapping[str, Any], forward_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if fit_artifact.get("status") != "DEVELOPMENT_ATTEMPT_PASS":
        raise ScoreCountForwardError("PASSING_DEVELOPMENT_FIT_REQUIRED")
    gate = fit_artifact.get("development_gate")
    if not isinstance(gate, Mapping) or gate.get("pass") is not True:
        raise ScoreCountForwardError("PASSING_DEVELOPMENT_GATE_REQUIRED")
    if prediction.get("fit_artifact_sha256") != fit_artifact.get("artifact_sha256"):
        raise ScoreCountForwardError("FIT_PREDICTION_IDENTITY_MISMATCH")
    rows_sha = sha256(json.dumps(
        [dict(x) for x in forward_rows], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    payload = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_BUNDLE_V1",
        "status": "FROZEN_PREGAME_RESEARCH_BUNDLE",
        "fit_artifact_sha256": fit_artifact["artifact_sha256"],
        "training_source_manifest_sha256": fit_artifact["source_manifest_sha256"],
        "forward_source_manifest_sha256": forward_manifest["manifest_sha256"],
        "forward_rows_sha256": rows_sha,
        "prediction_sha256": prediction["prediction_sha256"],
        "forward_source_manifest": dict(forward_manifest),
        "prediction": dict(prediction),
        "authority": "RESEARCH_ONLY_NO_PROMOTION_STAKING_OR_OFFICIAL_AUTHORITY",
    }
    payload["bundle_sha256"] = sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return payload
