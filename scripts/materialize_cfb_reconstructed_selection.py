#!/usr/bin/env python3
"""Materialize a reconstructed CFB selection bundle from private acquisition bytes.

This script performs no network calls and no model evaluation. The input payload is
expected to live in runner-private temporary storage. By default only hash-bound,
zero-authority manifests are written; normalized selection rows are written only
when an explicit private output path is supplied.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.reconstructed_selection import (
    CFBReconstructedSelectionError,
    build_selection_bundle_manifest,
    materialize_reconstructed_selection_rows,
)
from sportsedge.sports.cfb.source import CFBTeamMetrics

POLICY = ROOT / "config/cfb_model_selection_policy_v1.json"
PREDICTIVE_MANIFEST = ROOT / "config/cfb_model_candidate_code_manifest_v1.json"
EXPECTED_WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"


class CFBReconstructedMaterializationError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _code_manifest_sha256() -> str:
    paths = [
        ROOT / "sportsedge/sports/cfb/source.py",
        ROOT / "sportsedge/sports/cfb/reconstructed_selection.py",
        ROOT / "sportsedge/sports/cfb/candidate_history.py",
        ROOT / "scripts/materialize_cfb_reconstructed_selection.py",
        ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json",
    ]
    manifest = {str(path.relative_to(ROOT)): _sha_file(path) for path in paths}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _validate_preflight(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PRIVATE_PREFLIGHT_MISSING")
    if raw.get("schema_version") != "CFB_CFBD_PROVIDER_PREFLIGHT_V1":
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PRIVATE_PREFLIGHT_SCHEMA_INVALID")
    if raw.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PROVIDER_NOT_VERIFIED")
    if raw.get("weather_transport_ready") is not True:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_WEATHER_TRANSPORT_NOT_READY")
    if str(raw.get("weather_source_contract") or "").strip() != EXPECTED_WEATHER_CONTRACT:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_WEATHER_CONTRACT_MISMATCH")
    if raw.get("historical_replay_calls_performed") != 0:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PREFLIGHT_ALREADY_REPLAYED")
    try:
        remaining = int(raw["remaining_quota"])
        planned = int(raw["planned_new_calls"])
        reserve = int(raw["retry_reserve_calls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PREFLIGHT_QUOTA_INVALID") from exc
    if remaining < planned + reserve:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PREFLIGHT_QUOTA_INSUFFICIENT")
    authority = raw.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PREFLIGHT_AUTHORITY_LEAK")
    return raw


def _metric(raw: Mapping[str, Any]) -> CFBTeamMetrics:
    allowed = {field.name for field in fields(CFBTeamMetrics)}
    payload = {key: value for key, value in raw.items() if key in allowed}
    try:
        return CFBTeamMetrics(**payload)
    except TypeError as exc:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_METRIC_PAYLOAD_INVALID") from exc


def _membership(raw: object) -> dict[int, list[dict[str, Any]]]:
    if not isinstance(raw, Mapping):
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_MEMBERSHIP_INVALID")
    out: dict[int, list[dict[str, Any]]] = {}
    for season, rows in raw.items():
        try:
            year = int(season)
        except (TypeError, ValueError) as exc:
            raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_MEMBERSHIP_SEASON_INVALID") from exc
        if not isinstance(rows, list):
            raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_MEMBERSHIP_ROWS_INVALID")
        out[year] = [dict(row) for row in rows if isinstance(row, Mapping)]
    return out


def _assert_source_manifest(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_SOURCE_MANIFEST_MISSING")
    entries = raw.get("responses")
    if not isinstance(entries, list) or not entries:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_SOURCE_MANIFEST_EMPTY")
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise CFBReconstructedMaterializationError(f"CFB_RECONSTRUCTED_SOURCE_ENTRY_INVALID:{index}")
        for key in ("endpoint", "provider_contract", "query_sha256", "response_sha256", "retrieved_at_utc"):
            if not str(entry.get(key) or "").strip():
                raise CFBReconstructedMaterializationError(
                    f"CFB_RECONSTRUCTED_SOURCE_ENTRY_FIELD_MISSING:{index}:{key}"
                )
        for key in ("query_sha256", "response_sha256"):
            value = str(entry.get(key)).strip().lower()
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise CFBReconstructedMaterializationError(
                    f"CFB_RECONSTRUCTED_SOURCE_ENTRY_HASH_INVALID:{index}:{key}"
                )
    return raw


def run(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], Mapping[str, Any]]:
    if payload.get("schema") != "CFB_RECONSTRUCTED_ACQUISITION_PAYLOAD_V1":
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_SCHEMA_INVALID")
    _validate_preflight(payload.get("private_preflight"))
    source_manifest = _assert_source_manifest(payload.get("source_manifest"))

    games = payload.get("games")
    metric_rows = payload.get("metrics")
    weather = payload.get("weather_by_game")
    if not isinstance(games, list) or not isinstance(metric_rows, list) or not isinstance(weather, Mapping):
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_COMPONENTS_INVALID")

    rows = materialize_reconstructed_selection_rows(
        games=[dict(row) for row in games if isinstance(row, Mapping)],
        metrics=[_metric(row) for row in metric_rows if isinstance(row, Mapping)],
        weather_by_game={str(key): dict(value) for key, value in weather.items() if isinstance(value, Mapping)},
        fbs_membership_by_season=_membership(payload.get("fbs_membership_by_season")),
    )
    policy = _load(POLICY)
    weather_contract = str(payload.get("weather_source_contract") or "").strip()
    if weather_contract != EXPECTED_WEATHER_CONTRACT:
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_WEATHER_CONTRACT_MISMATCH")
    bundle = build_selection_bundle_manifest(
        rows=rows,
        source_manifest=source_manifest,
        policy=policy,
        predictive_code_manifest_sha256=_sha_file(PREDICTIVE_MANIFEST),
        acquisition_code_manifest_sha256=_code_manifest_sha256(),
        weather_source_contract=weather_contract,
    )
    return rows, bundle, source_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-input", type=Path, required=True)
    parser.add_argument("--bundle-out", type=Path, required=True)
    parser.add_argument("--source-manifest-out", type=Path, required=True)
    parser.add_argument("--private-rows-out", type=Path)
    args = parser.parse_args(argv)

    try:
        payload = _load(args.private_input)
        if not isinstance(payload, Mapping):
            raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_NOT_OBJECT")
        rows, bundle, source_manifest = run(payload)
    except (CFBReconstructedMaterializationError, CFBReconstructedSelectionError) as exc:
        print(json.dumps({
            "status": "BLOCKED_RECONSTRUCTED_MATERIALIZATION",
            "reason": str(exc),
            "attempt_consumed": False,
            "evaluation_performed": False,
            "historical_pit_created": False,
            "model_p_created": False,
            "promotion_authority": False,
            "eligibility_changed": False,
            "official_authority": False,
        }, sort_keys=True))
        return 2

    args.bundle_out.parent.mkdir(parents=True, exist_ok=True)
    args.bundle_out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.source_manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.source_manifest_out.write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.private_rows_out is not None:
        args.private_rows_out.parent.mkdir(parents=True, exist_ok=True)
        args.private_rows_out.write_text(json.dumps(rows, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": bundle["status"],
        "selection_row_count": bundle["selection_row_count"],
        "selection_rows_sha256": bundle["selection_rows_sha256"],
        "source_manifest_sha256": bundle["source_manifest_sha256"],
        "attempt_consumed": False,
        "evaluation_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
