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
    canonical_sha256,
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
        ROOT / "scripts/preflight_cfb_reconstructed_selection.py",
        ROOT / "scripts/acquire_cfb_reconstructed_selection.py",
        ROOT / "scripts/materialize_cfb_reconstructed_selection.py",
        ROOT / "sportsedge/sports/cfb/source.py",
        ROOT / "sportsedge/sports/cfb/venue_coordinates.py",
        ROOT / "sportsedge/sports/cfb/reconstructed_selection.py",
        ROOT / "sportsedge/sports/cfb/candidate_history.py",
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


def _zero_authority() -> dict[str, bool]:
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
        "backfill": False,
    }


def _public_acquisition_readiness(
    *,
    preflight: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a durable readiness proof without exposing account quota values."""
    if preflight.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        raise CFBReconstructedMaterializationError(
            "CFB_RECONSTRUCTED_PUBLIC_READINESS_PREFLIGHT_NOT_VERIFIED"
        )
    try:
        monthly = int(preflight["monthly_quota"])
        remaining = int(preflight["remaining_quota"])
        planned = int(preflight["planned_new_calls"])
        retry = int(preflight["retry_reserve_calls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBReconstructedMaterializationError(
            "CFB_RECONSTRUCTED_PUBLIC_READINESS_QUOTA_PROOF_INVALID"
        ) from exc
    if monthly <= 0 or remaining < planned + retry:
        raise CFBReconstructedMaterializationError(
            "CFB_RECONSTRUCTED_PUBLIC_READINESS_QUOTA_NOT_VERIFIED"
        )
    responses = source_manifest.get("responses")
    if not isinstance(responses, list) or not responses:
        raise CFBReconstructedMaterializationError(
            "CFB_RECONSTRUCTED_PUBLIC_READINESS_CACHE_MANIFEST_MISSING"
        )
    cache_manifest = []
    for raw in responses:
        if not isinstance(raw, Mapping):
            raise CFBReconstructedMaterializationError(
                "CFB_RECONSTRUCTED_PUBLIC_READINESS_CACHE_ENTRY_INVALID"
            )
        cache_manifest.append({
            "endpoint": raw.get("endpoint"),
            "season": raw.get("season"),
            "end_week": raw.get("end_week"),
            "provider_contract": raw.get("provider_contract"),
            "query_sha256": raw.get("query_sha256"),
            "response_sha256": raw.get("response_sha256"),
            "retrieved_at_utc": raw.get("retrieved_at_utc"),
        })
    private_proof = {
        "status": preflight.get("status"),
        "active_cfbd_tier": preflight.get("active_cfbd_tier"),
        "patron_level": preflight.get("patron_level"),
        "monthly_quota": monthly,
        "remaining_quota": remaining,
        "planned_new_calls": planned,
        "retry_reserve_calls": retry,
        "verified_cache_reuse": preflight.get("verified_cache_reuse"),
        "resume_from_verified_cache": preflight.get("resume_from_verified_cache"),
        "restart_from_2015": preflight.get("restart_from_2015"),
        "retry_backoff": preflight.get("retry_backoff"),
    }
    return {
        "schema": "CFB_RECONSTRUCTED_ACQUISITION_READINESS_PUBLIC_V1",
        "status": "ACQUISITION_COMPLETE_READY_FOR_SELECTION",
        "account_info_verified": True,
        "tier_quota_mapping_verified": True,
        "call_plan_fits_verified_quota": True,
        "planned_new_calls": planned,
        "retry_reserve_calls": retry,
        "verified_cache_reuse": preflight.get("verified_cache_reuse") is True,
        "resume_from_verified_cache": preflight.get("resume_from_verified_cache") is True,
        "restart_from_2015": bool(preflight.get("restart_from_2015")),
        "retry_backoff": preflight.get("retry_backoff") is True,
        "source_manifest_sha256": canonical_sha256(source_manifest),
        "preflight_proof_sha256": canonical_sha256(private_proof),
        "cache_manifest": cache_manifest,
        "quota_values_redacted": True,
        "raw_provider_data_persisted_publicly": False,
        "authority": _zero_authority(),
    }


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


def run(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], Mapping[str, Any], dict[str, Any]]:
    if payload.get("schema") != "CFB_RECONSTRUCTED_ACQUISITION_PAYLOAD_V1":
        raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_SCHEMA_INVALID")
    preflight = _validate_preflight(payload.get("private_preflight"))
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
    acquisition_readiness = _public_acquisition_readiness(
        preflight=preflight,
        source_manifest=source_manifest,
    )
    return rows, bundle, source_manifest, acquisition_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-input", type=Path, required=True)
    parser.add_argument("--bundle-out", type=Path, required=True)
    parser.add_argument("--source-manifest-out", type=Path, required=True)
    parser.add_argument("--acquisition-manifest-out", type=Path)
    parser.add_argument("--private-rows-out", type=Path)
    args = parser.parse_args(argv)

    try:
        payload = _load(args.private_input)
        if not isinstance(payload, Mapping):
            raise CFBReconstructedMaterializationError("CFB_RECONSTRUCTED_PAYLOAD_NOT_OBJECT")
        rows, bundle, source_manifest, acquisition_readiness = run(payload)
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
    if args.acquisition_manifest_out is not None:
        args.acquisition_manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.acquisition_manifest_out.write_text(
            json.dumps(acquisition_readiness, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.private_rows_out is not None:
        args.private_rows_out.parent.mkdir(parents=True, exist_ok=True)
        args.private_rows_out.write_text(json.dumps(rows, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": bundle["status"],
        "selection_row_count": bundle["selection_row_count"],
        "selection_rows_sha256": bundle["selection_rows_sha256"],
        "source_manifest_sha256": bundle["source_manifest_sha256"],
        "acquisition_readiness_status": acquisition_readiness["status"],
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
