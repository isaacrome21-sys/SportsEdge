#!/usr/bin/env python3
"""Executable fail-closed NFL M2 RUN IT lane.

No model fitting occurs here. A frozen, hash-bound NFL M2 artifact, its exact
promotion registry, and the frozen Truth Gate floor registry are external inputs
to production resolution. The preferred binding is the exact runtime Git SHA.
A frozen artifact may survive unrelated repository commits only when its freeze
registry also pins a byte-exact NFL M2 code-surface manifest and that manifest
verifies against the current checkout. The original fit SHA remains artifact
provenance; compatibility never upgrades promotion evidence.

Manual odds snapshots must already contain their real ``observed_at`` timestamp;
this script never rewrites an old quote timestamp to make the 180-second TTL pass.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.code_surface import (
    NFLCodeSurfaceError,
    load_and_verify_nfl_m2_code_surface,
)
from sportsedge.sports.nfl.live_features import build_nfl_live_feature_payload
from sportsedge.sports.nfl.odds_source import fetch_nfl_odds
from sportsedge.sports.nfl.readiness import load_nfl_promotion_registry, run_nfl_ready
from sportsedge.sports.nfl.run_machine import (
    DEFAULT_FEATURE_TTL_SECONDS,
    DEFAULT_QUOTE_TTL_SECONDS,
    NFLRunMachineError,
)

_KEYS = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)
_DEFAULT_FREEZE_REGISTRY = _REPO_ROOT / "config" / "nfl_m2_freeze.json"
_DEFAULT_PROMOTION_REGISTRY = _REPO_ROOT / "artifacts" / "football" / "nfl_promotion_registry.json"
_DEFAULT_FLOOR_REGISTRY = _REPO_ROOT / "config" / "truth_gate_floors.json"


class NFLAutoError(ValueError):
    pass


def _utc(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise NFLAutoError("NFL_AUTO_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLAutoError("NFL_AUTO_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _json(path: Path, error: str) -> dict[str, Any]:
    if not path.is_file():
        raise NFLAutoError(error)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NFLAutoError(error) from exc
    if not isinstance(payload, dict):
        raise NFLAutoError(error)
    return payload


def _runtime_git_sha(override: str | None) -> str:
    if override:
        value = str(override).strip().lower()
    else:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise NFLAutoError("NFL_AUTO_RUNTIME_GIT_SHA_UNAVAILABLE")
        value = completed.stdout.strip().lower()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise NFLAutoError("NFL_AUTO_RUNTIME_GIT_SHA_INVALID")
    return value


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _operator_payload(path: Path | None, error: str) -> dict[str, Any] | None:
    return None if path is None else _json(path, error)


def _odds_keys() -> list[str]:
    keys = [str(os.environ.get(name) or "").strip() for name in _KEYS]
    keys = [key for key in keys if key]
    if not keys:
        raise NFLAutoError("NFL_AUTO_ODDS_API_KEY_REQUIRED")
    return keys


def _env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name) or "").strip()
    return Path(raw) if raw else None


def _artifact_path(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (_REPO_ROOT / path).resolve()


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLAutoError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLAutoError(error)
    return raw


def _frozen_artifact_hash(
    candidate_path: Path,
    freeze_registry: Path,
    runtime_sha: str,
) -> tuple[str, str, dict[str, Any] | None]:
    """Resolve artifact hash + model binding SHA without laundering provenance.

    Exact-head binding remains the normal path. If the fitted artifact predates
    unrelated repository commits, compatibility is accepted only when the FROZEN
    registry pins a code-surface manifest by SHA-256 and every file in that
    manifest is byte-identical in the current checkout. The returned binding SHA
    is always the artifact's original fit SHA, never a fabricated refit identity.
    """
    freeze = _json(freeze_registry, "NFL_AUTO_FROZEN_MODEL_BINDING_REQUIRED")
    if freeze.get("schema_version") != 1:
        raise NFLAutoError("NFL_AUTO_FROZEN_MODEL_BINDING_SCHEMA_INVALID")
    if freeze.get("hash_algorithm") != "CANONICAL_JSON_SHA256_V1":
        raise NFLAutoError("NFL_AUTO_FROZEN_MODEL_HASH_ALGORITHM_INVALID")
    if str(freeze.get("status") or "").upper() != "FROZEN":
        raise NFLAutoError("NFL_AUTO_FROZEN_MODEL_BINDING_REQUIRED")
    declared_path = str(freeze.get("artifact_path") or "").strip()
    if not declared_path:
        raise NFLAutoError("NFL_AUTO_FROZEN_MODEL_ARTIFACT_PATH_REQUIRED")

    if freeze_registry.resolve() == _DEFAULT_FREEZE_REGISTRY.resolve():
        frozen_path = (_REPO_ROOT / declared_path).resolve()
        if candidate_path != frozen_path:
            raise NFLAutoError("NFL_AUTO_MODEL_ARTIFACT_PATH_NOT_FROZEN")
    digest = _sha256(
        freeze.get("artifact_sha256"), "NFL_AUTO_FROZEN_MODEL_SHA256_INVALID"
    )
    fit_sha = _git_sha(
        freeze.get("code_git_sha") or runtime_sha,
        "NFL_AUTO_FROZEN_MODEL_CODE_SHA_INVALID",
    )
    if fit_sha == runtime_sha:
        return digest, fit_sha, None

    compatibility = freeze.get("compatible_runtime")
    if not isinstance(compatibility, Mapping):
        raise NFLAutoError("NFL_AUTO_FROZEN_MODEL_CODE_SHA_MISMATCH")
    if compatibility.get("mode") != "NFL_M2_CODE_SURFACE_V1":
        raise NFLAutoError("NFL_AUTO_CODE_SURFACE_MODE_INVALID")
    manifest_path = str(compatibility.get("manifest_path") or "").strip()
    if not manifest_path:
        raise NFLAutoError("NFL_AUTO_CODE_SURFACE_MANIFEST_REQUIRED")
    manifest_sha = _sha256(
        compatibility.get("manifest_sha256"),
        "NFL_AUTO_CODE_SURFACE_MANIFEST_SHA256_INVALID",
    )
    try:
        verified = load_and_verify_nfl_m2_code_surface(
            manifest_path,
            repo_root=_REPO_ROOT,
            expected_sha256=manifest_sha,
            expected_fit_git_sha=fit_sha,
        )
    except NFLCodeSurfaceError as exc:
        raise NFLAutoError(str(exc)) from exc
    return digest, fit_sha, verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="AUTO_SELECT", choices=("AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"))
    parser.add_argument("--asof")
    parser.add_argument("--model-artifact", type=Path)
    parser.add_argument("--freeze-registry", type=Path)
    parser.add_argument("--promotion-registry", type=Path)
    parser.add_argument("--floor-registry", type=Path)
    parser.add_argument("--runtime-code-git-sha")
    parser.add_argument("--live-features", type=Path)
    parser.add_argument("--odds-snapshot", type=Path)
    parser.add_argument("--book-key", default="draftkings")
    parser.add_argument("--quote-ttl-seconds", type=int, default=DEFAULT_QUOTE_TTL_SECONDS)
    parser.add_argument("--feature-ttl-seconds", type=int, default=DEFAULT_FEATURE_TTL_SECONDS)
    parser.add_argument("--schedule-file", type=Path, default=Path("artifacts/football/sources/games.csv"))
    parser.add_argument("--pbp-dir", type=Path, default=Path("artifacts/football/sources/pbp"))
    parser.add_argument("--participation-dir", type=Path, default=Path("artifacts/football/sources/participation"))
    parser.add_argument("--depth-dir", type=Path, default=Path("artifacts/football/sources/depth"))
    parser.add_argument("--stadium-file", type=Path, default=Path("artifacts/football/sources/team_stadiums.csv"))
    parser.add_argument("--start-season", type=int, default=2016)
    parser.add_argument("--current-season", type=int)
    parser.add_argument("--horizon-minutes", type=int, default=120)
    parser.add_argument("--min-lead-minutes", type=int, default=45)
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/nfl_card.json"))
    args = parser.parse_args()

    current = _utc(args.asof)
    try:
        actual_runtime_sha = _runtime_git_sha(args.runtime_code_git_sha)
        model_arg = args.model_artifact or _env_path("SPORTSEDGE_NFL_M2_MODEL_ARTIFACT_PATH") or Path("artifacts/football/nfl_m2_model.json")
        freeze_registry = args.freeze_registry or _env_path("SPORTSEDGE_NFL_M2_FREEZE_REGISTRY_PATH") or _DEFAULT_FREEZE_REGISTRY
        promotion_registry_path = args.promotion_registry or _env_path("SPORTSEDGE_NFL_PROMOTION_REGISTRY_PATH") or _DEFAULT_PROMOTION_REGISTRY
        floor_registry = args.floor_registry or _env_path("SPORTSEDGE_TRUTH_GATE_FLOOR_PATH") or _DEFAULT_FLOOR_REGISTRY
        model_path = _artifact_path(model_arg)

        artifact = _json(model_path, "NFL_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
        expected_artifact_sha, model_binding_sha, compatibility = _frozen_artifact_hash(
            model_path, freeze_registry, actual_runtime_sha
        )
        promotion_registry = load_nfl_promotion_registry(promotion_registry_path)
        if not floor_registry.is_file():
            raise NFLAutoError("NFL_AUTO_TRUTH_GATE_FLOOR_REGISTRY_REQUIRED")
        supplied_features = _operator_payload(args.live_features, "NFL_AUTO_LIVE_FEATURES_UNREADABLE")
        supplied_odds = _operator_payload(args.odds_snapshot, "NFL_AUTO_ODDS_SNAPSHOT_UNREADABLE")

        needs_network_odds = supplied_odds is None and str(args.mode).upper() in ("AUTO_SELECT", "HYBRID", "AUTOMATIC")
        if needs_network_odds and args.asof is not None:
            raise NFLAutoError("NFL_AUTO_NETWORK_ODDS_WITH_EXPLICIT_ASOF_PROHIBITED")
        execution_now = datetime.now(timezone.utc) if args.asof is None else current

        def build_features() -> dict[str, Any]:
            return build_nfl_live_feature_payload(
                schedule_file=args.schedule_file, pbp_dir=args.pbp_dir,
                participation_dir=args.participation_dir, depth_dir=args.depth_dir,
                stadium_file=args.stadium_file, asof=execution_now,
                start_season=int(args.start_season),
                current_season=int(args.current_season if args.current_season is not None else execution_now.year),
                horizon_minutes=int(args.horizon_minutes), min_lead_minutes=int(args.min_lead_minutes),
            )

        def fetch_odds() -> dict[str, Any]:
            result = fetch_nfl_odds(_odds_keys())
            payload = result.value
            if not isinstance(payload, list):
                raise NFLAutoError("NFL_AUTO_ODDS_PROVIDER_PAYLOAD_INVALID")
            return {
                "schema_version": 1, "sport": "nfl", "source": "the-odds-api",
                "observed_at": execution_now.isoformat(), "events": payload,
                "key_slot": result.key_slot, "prior_key_failures": len(result.failures),
            }

        report = run_nfl_ready(
            promotion_registry=promotion_registry,
            floor_path=floor_registry,
            mode=str(args.mode).upper(),
            model_artifact=artifact,
            expected_model_artifact_sha256=expected_artifact_sha,
            runtime_code_git_sha=model_binding_sha,
            now=execution_now,
            live_features=supplied_features,
            odds_snapshot=supplied_odds,
            feature_builder=build_features,
            odds_fetcher=fetch_odds,
            book_key=args.book_key,
            quote_ttl_seconds=int(args.quote_ttl_seconds),
            feature_ttl_seconds=int(args.feature_ttl_seconds),
        )
        payload = {
            "schema_version": "NFL_AUTO_RUN_V2",
            "status": "SUCCESS",
            "report": report.to_dict(),
            "runtime_code_git_sha": actual_runtime_sha,
            "model_binding_git_sha": model_binding_sha,
            "compatible_code_surface": compatibility,
            "governance": {
                "model_fit_performed": False,
                "model_fit_identity_rewritten": False,
                "market_prices_are_model_features": False,
                "promotion_registry_resolved": True,
                "truth_gate_resolution_performed": True,
                "manual_eligible_toggle_required": False,
                "code_surface_compatibility_may_upgrade_promotion": False,
                "fail_closed": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps({
            "status": "SUCCESS", "mode": report.mode, "run_status": report.run_status,
            "priced": report.summary["priced"], "official_bets": report.summary["official_bets"],
            "output": str(args.output),
        }, sort_keys=True))
        return 0
    except (NFLAutoError, NFLRunMachineError, ValueError) as exc:
        payload = {
            "schema_version": "NFL_AUTO_RUN_V2", "status": "BLOCKED",
            "blocker": str(exc), "generated_at_utc": current.isoformat(),
            "governance": {
                "model_fit_performed": False,
                "promotion_registry_resolved": True,
                "truth_gate_resolution_performed": True,
                "manual_eligible_toggle_required": False,
                "fail_closed": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
