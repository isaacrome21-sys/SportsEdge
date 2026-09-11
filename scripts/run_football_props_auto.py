#!/usr/bin/env python3
"""Fail-closed NFL/CFB player-prop entrypoint.

A real fitted artifact and fresh PIT opportunity/usage snapshot are mandatory.
Market prices enter only after Model_P exists. Frozen artifacts may execute only
at their exact fit commit or through an independently hash-bound predictive code
surface; promotion remains independently evidence/Truth-Gate gated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_prop_odds_source import build_odds_snapshot, fetch_event_prop_odds
from sportsedge.football_prop_run_machine import FootballPropRunError
from sportsedge.football_prop_readiness import run_football_props_ready
from sportsedge.sports.nfl.prop_code_surface import (
    CFBPropCodeSurfaceError,
    NFLPropCodeSurfaceError,
    load_nfl_prop_artifact_bundle,
    verify_cfb_prop_code_surface,
    verify_nfl_prop_code_surface,
)


class FootballPropAutoError(ValueError):
    pass


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FootballPropAutoError("FOOTBALL_PROP_AUTO_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise FootballPropAutoError("FOOTBALL_PROP_AUTO_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _json(path: Path, error: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FootballPropAutoError(error) from exc
    if not isinstance(value, dict):
        raise FootballPropAutoError(error)
    return value


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _runtime_git_sha() -> str:
    override = str(os.environ.get("SPORTSEDGE_CODE_GIT_SHA") or "").strip().lower()
    if override:
        if len(override) != 40 or any(ch not in "0123456789abcdef" for ch in override):
            raise FootballPropAutoError("FOOTBALL_PROP_RUNTIME_CODE_GIT_SHA_INVALID")
        return override
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip().lower()
    except Exception as exc:
        raise FootballPropAutoError("FOOTBALL_PROP_RUNTIME_CODE_GIT_SHA_REQUIRED") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise FootballPropAutoError("FOOTBALL_PROP_RUNTIME_CODE_GIT_SHA_INVALID")
    return value


def _defaults(sport: str) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    lower = sport.lower()
    artifact = (
        Path("artifacts/football/nfl_prop_artifact_bundle_v1.json")
        if sport == "NFL"
        else Path(f"artifacts/football/{lower}_offensive_prop_ab_model.json")
    )
    return (
        Path(f"config/{lower}_prop_model_freeze.json"),
        Path(f"config/{lower}_prop_evidence.json"),
        Path(f"config/{lower}_prop_certification.json"),
        Path("config/truth_gate_floors.json"),
        artifact,
        Path(f"artifacts/football/{lower}_prop_live_features.json"),
        Path(f"artifacts/football/{lower}_prop_odds_snapshot.json"),
    )


def _env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name) or "").strip()
    return Path(raw) if raw else None


def _load_artifact_file(path: Path, sport: str) -> dict:
    if sport == "NFL":
        try:
            maybe_bundle = _json(path, f"{sport}_PROP_MODEL_ARTIFACT_INVALID")
            if maybe_bundle.get("schema_version") == "FOOTBALL_PROP_ARTIFACT_BUNDLE_V1":
                return load_nfl_prop_artifact_bundle(root=ROOT, bundle_path=path)
        except FootballPropAutoError:
            raise
        except NFLPropCodeSurfaceError as exc:
            raise FootballPropAutoError(str(exc)) from exc
    return _json(path, f"{sport}_PROP_MODEL_ARTIFACT_INVALID")


def _freeze(registry_path: Path, artifact_path: Path, sport: str) -> tuple[dict, str, dict]:
    if not registry_path.is_file():
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_BINDING_REQUIRED")
    registry = _json(registry_path, f"{sport}_PROP_FREEZE_REGISTRY_INVALID")
    if registry.get("sport") != sport or registry.get("status") != "FROZEN":
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_BINDING_REQUIRED")
    if registry.get("hash_algorithm") != "CANONICAL_JSON_SHA256_V1":
        raise FootballPropAutoError(f"{sport}_PROP_FREEZE_HASH_ALGORITHM_INVALID")
    if registry.get("promotion_authority") is not False:
        raise FootballPropAutoError(f"{sport}_PROP_FREEZE_PROMOTION_AUTHORITY_INVALID")
    expected = str(registry.get("artifact_sha256") or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_SHA256_INVALID")
    if not artifact_path.is_file():
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_ARTIFACT_REQUIRED")
    checked_in_registry = (ROOT / f"config/{sport.lower()}_prop_model_freeze.json").resolve()
    if registry_path.resolve() == checked_in_registry:
        declared = (ROOT / str(registry.get("artifact_path") or "")).resolve()
        if declared != artifact_path.resolve():
            raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_BINDING_REQUIRED")
    artifact = _load_artifact_file(artifact_path, sport)
    artifact_code = str(artifact.get("code_git_sha") or "").strip().lower()
    freeze_code = str(registry.get("code_git_sha") or "").strip().lower()
    if not artifact_code or freeze_code != artifact_code:
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_CODE_SHA_MISMATCH")
    return artifact, expected, registry


def _runtime_model_code_sha(*, sport: str, registry: dict, artifact: dict) -> tuple[str, dict]:
    fit_sha = str(artifact.get("code_git_sha") or "").strip().lower()
    runtime_sha = _runtime_git_sha()
    if fit_sha == runtime_sha:
        return fit_sha, {"status": "EXACT_FIT_COMMIT", "fit_git_sha": fit_sha, "promotion_authority": False}
    try:
        if sport == "NFL":
            attestation = verify_nfl_prop_code_surface(root=ROOT, registry=registry, artifact=artifact)
        elif sport == "CFB":
            attestation = verify_cfb_prop_code_surface(root=ROOT, registry=registry, artifact=artifact)
        else:
            raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_CODE_SHA_MISMATCH")
    except (NFLPropCodeSurfaceError, CFBPropCodeSurfaceError) as exc:
        raise FootballPropAutoError(str(exc)) from exc
    return fit_sha, attestation


def _odds_from_network(*, sport: str, features: dict, current: datetime) -> dict:
    keys = [
        str(os.environ.get(name) or "").strip()
        for name in (
            "SPORTSEDGE_ODDS_API_KEY",
            "SPORTSEDGE_ODDS_API_KEY_2",
            "SPORTSEDGE_ODDS_API_KEY_3",
            "SPORTSEDGE_ODDS_API_KEY_4",
            "ODDS_API_KEY",
        )
    ]
    keys = [key for key in keys if key]
    if not keys:
        raise FootballPropAutoError(f"{sport}_PROP_ODDS_API_KEY_REQUIRED")
    games = features.get("games")
    if not isinstance(games, list) or not games:
        raise FootballPropAutoError(f"{sport}_PROP_LIVE_FEATURE_GAMES_EMPTY")
    events, seen = [], set()
    for game in games:
        if not isinstance(game, dict):
            raise FootballPropAutoError(f"{sport}_PROP_LIVE_FEATURE_GAME_INVALID")
        event_id = str(game.get("provider_event_id") or "").strip()
        if not event_id:
            raise FootballPropAutoError(f"{sport}_PROP_PROVIDER_EVENT_ID_REQUIRED")
        if event_id in seen:
            continue
        seen.add(event_id)
        events.append(dict(fetch_event_prop_odds(keys, sport=sport, event_id=event_id).value))
    return build_odds_snapshot(events, observed_at=current)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=("NFL", "CFB"))
    ap.add_argument("--asof")
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--evidence-registry", type=Path)
    ap.add_argument("--certification-registry", type=Path)
    ap.add_argument("--floor-registry", type=Path)
    ap.add_argument("--model-artifact", type=Path)
    ap.add_argument("--live-features", type=Path)
    ap.add_argument("--odds-snapshot", type=Path)
    ap.add_argument("--bookmaker", default="draftkings")
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260909)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    sport = args.sport.upper()
    defaults = _defaults(sport)
    registry_path = args.registry or _env_path(f"SPORTSEDGE_{sport}_PROP_FREEZE_REGISTRY_PATH") or defaults[0]
    evidence_path = args.evidence_registry or _env_path(f"SPORTSEDGE_{sport}_PROP_EVIDENCE_REGISTRY_PATH") or defaults[1]
    certification_path = args.certification_registry or _env_path(f"SPORTSEDGE_{sport}_PROP_CERTIFICATION_REGISTRY_PATH") or defaults[2]
    floor_path = args.floor_registry or _env_path("SPORTSEDGE_TRUTH_GATE_FLOOR_PATH") or defaults[3]
    artifact_path = args.model_artifact or _env_path(f"SPORTSEDGE_{sport}_PROP_MODEL_ARTIFACT_PATH") or defaults[4]
    feature_path = args.live_features or _env_path(f"SPORTSEDGE_{sport}_PROP_LIVE_FEATURES_PATH") or defaults[5]
    odds_path = args.odds_snapshot or _env_path(f"SPORTSEDGE_{sport}_PROP_ODDS_SNAPSHOT_PATH") or defaults[6]
    output = args.output or Path(f"artifacts/run_it/{sport.lower()}_prop_card.json")
    current = _utc(args.asof)
    try:
        artifact, expected_sha, registry = _freeze(registry_path, artifact_path, sport)
        runtime_model_sha, code_attestation = _runtime_model_code_sha(sport=sport, registry=registry, artifact=artifact)
        if not evidence_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_EVIDENCE_REGISTRY_REQUIRED")
        if not certification_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_CERTIFICATION_REGISTRY_REQUIRED")
        if not floor_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_TRUTH_GATE_FLOOR_REGISTRY_REQUIRED")
        evidence_registry = _json(evidence_path, f"{sport}_PROP_EVIDENCE_REGISTRY_INVALID")
        certification_registry = _json(certification_path, f"{sport}_PROP_CERTIFICATION_REGISTRY_INVALID")
        if not feature_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_PIT_LIVE_FEATURE_SNAPSHOT_REQUIRED")
        features = _json(feature_path, f"{sport}_PROP_PIT_LIVE_FEATURE_SNAPSHOT_INVALID")
        odds = _json(odds_path, f"{sport}_PROP_ODDS_SNAPSHOT_INVALID") if odds_path.is_file() else _odds_from_network(sport=sport, features=features, current=current)
        report = run_football_props_ready(
            sport=sport,
            evidence_registry=evidence_registry,
            certification_registry=certification_registry,
            floor_path=str(floor_path),
            now=current,
            artifact_payload=artifact,
            expected_artifact_sha256=expected_sha,
            runtime_code_git_sha=runtime_model_sha,
            live_features=features,
            odds_snapshot=odds,
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
            book_key=str(args.bookmaker),
        )
        payload = {
            "schema_version": "FOOTBALL_PROP_AUTO_RUN_V4",
            "status": "SUCCESS",
            "sport": sport,
            "report": report,
            "model_code_attestation": code_attestation,
            "governance": {
                "model_fit_performed": False,
                "evidence_resolution_performed": True,
                "certification_resolution_performed": True,
                "truth_gate_resolution_performed": True,
                "manual_promotion_toggle_required": False,
                "fail_closed": True,
                "code_surface_compatibility_can_promote": False,
            },
        }
        _write(output, payload)
        print(json.dumps({"status": "SUCCESS", "sport": sport, "output": str(output)}, sort_keys=True))
        return 0
    except (FootballPropAutoError, FootballPropRunError, ValueError) as exc:
        payload = {
            "schema_version": "FOOTBALL_PROP_AUTO_RUN_V4",
            "status": "BLOCKED",
            "sport": sport,
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "report": {
                "run_status": "BLOCKED",
                "results": [{"sport": sport, "market": "FOOTBALL_PLAYER_PROPS", "model_p": None, "bet_status": "BLOCKED", "reason": str(exc)}],
            },
            "governance": {
                "model_fit_performed": False,
                "evidence_resolution_performed": True,
                "certification_resolution_performed": True,
                "truth_gate_resolution_performed": True,
                "manual_promotion_toggle_required": False,
                "fail_closed": True,
                "code_surface_compatibility_can_promote": False,
            },
        }
        _write(output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
