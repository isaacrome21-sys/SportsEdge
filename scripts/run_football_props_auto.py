#!/usr/bin/env python3
"""Fail-closed NFL/CFB player-prop entrypoint.

A real fitted artifact and a fresh PIT opportunity/usage snapshot are mandatory.
Market prices can be supplied as a captured snapshot or acquired event-by-event
from The Odds API. Resolution always passes through the artifact-bound evidence
readiness layer. This script never fits, promotes, or changes Truth Gate state.
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


def _defaults(sport: str) -> tuple[Path, Path, Path, Path, Path]:
    lower = sport.lower()
    return (
        Path(f"config/{lower}_prop_model_freeze.json"),
        Path(f"config/{lower}_prop_evidence.json"),
        Path(f"artifacts/football/{lower}_offensive_prop_ab_model.json"),
        Path(f"artifacts/football/{lower}_prop_live_features.json"),
        Path(f"artifacts/football/{lower}_prop_odds_snapshot.json"),
    )


def _freeze(registry_path: Path, artifact_path: Path, sport: str) -> tuple[dict, str]:
    # Missing fitted bytes are the first blocker. Merely placing arbitrary bytes
    # at the path still cannot bypass the independent freeze registry below.
    if not artifact_path.is_file():
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_ARTIFACT_REQUIRED")
    if not registry_path.is_file():
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_BINDING_REQUIRED")
    registry = _json(registry_path, f"{sport}_PROP_FREEZE_REGISTRY_INVALID")
    if registry.get("sport") != sport or registry.get("status") != "FROZEN":
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_BINDING_REQUIRED")
    if registry.get("hash_algorithm") != "CANONICAL_JSON_SHA256_V1":
        raise FootballPropAutoError(f"{sport}_PROP_FREEZE_HASH_ALGORITHM_INVALID")
    expected = str(registry.get("artifact_sha256") or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_SHA256_INVALID")
    declared = ROOT / str(registry.get("artifact_path") or "")
    if declared.resolve() != artifact_path.resolve():
        raise FootballPropAutoError(f"{sport}_PROP_FROZEN_MODEL_PATH_MISMATCH")
    return _json(artifact_path, f"{sport}_PROP_MODEL_ARTIFACT_INVALID"), expected


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
    events = []
    seen = set()
    for game in games:
        if not isinstance(game, dict):
            raise FootballPropAutoError(f"{sport}_PROP_LIVE_FEATURE_GAME_INVALID")
        event_id = str(game.get("provider_event_id") or "").strip()
        if not event_id:
            raise FootballPropAutoError(f"{sport}_PROP_PROVIDER_EVENT_ID_REQUIRED")
        if event_id in seen:
            continue
        seen.add(event_id)
        result = fetch_event_prop_odds(keys, sport=sport, event_id=event_id)
        events.append(dict(result.value))
    return build_odds_snapshot(events, observed_at=current)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=("NFL", "CFB"))
    ap.add_argument("--asof")
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--evidence-registry", type=Path)
    ap.add_argument("--model-artifact", type=Path)
    ap.add_argument("--live-features", type=Path)
    ap.add_argument("--odds-snapshot", type=Path)
    ap.add_argument("--bookmaker", default="draftkings")
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260909)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    sport = args.sport.upper()
    default_registry, default_evidence, default_artifact, default_features, default_odds = _defaults(sport)
    registry_path = args.registry or default_registry
    evidence_path = args.evidence_registry or default_evidence
    artifact_path = args.model_artifact or default_artifact
    feature_env = os.environ.get(f"SPORTSEDGE_{sport}_PROP_LIVE_FEATURES_PATH")
    odds_env = os.environ.get(f"SPORTSEDGE_{sport}_PROP_ODDS_SNAPSHOT_PATH")
    feature_path = args.live_features or (Path(feature_env) if feature_env else default_features)
    odds_path = args.odds_snapshot or (Path(odds_env) if odds_env else default_odds)
    output = args.output or Path(f"artifacts/run_it/{sport.lower()}_prop_card.json")
    current = _utc(args.asof)

    try:
        artifact, expected_sha = _freeze(registry_path, artifact_path, sport)
        if not evidence_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_EVIDENCE_REGISTRY_REQUIRED")
        evidence_registry = _json(evidence_path, f"{sport}_PROP_EVIDENCE_REGISTRY_INVALID")
        if not feature_path.is_file():
            raise FootballPropAutoError(f"{sport}_PROP_PIT_LIVE_FEATURE_SNAPSHOT_REQUIRED")
        features = _json(feature_path, f"{sport}_PROP_PIT_LIVE_FEATURE_SNAPSHOT_INVALID")
        odds = (
            _json(odds_path, f"{sport}_PROP_ODDS_SNAPSHOT_INVALID")
            if odds_path.is_file()
            else _odds_from_network(sport=sport, features=features, current=current)
        )
        report = run_football_props_ready(
            sport=sport,
            evidence_registry=evidence_registry,
            now=current,
            artifact_payload=artifact,
            expected_artifact_sha256=expected_sha,
            runtime_code_git_sha=_runtime_git_sha(),
            live_features=features,
            odds_snapshot=odds,
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
            book_key=str(args.bookmaker),
        )
        payload = {
            "schema_version": "FOOTBALL_PROP_AUTO_RUN_V2",
            "status": "SUCCESS",
            "sport": sport,
            "report": report,
            "governance": {
                "model_fit_performed": False,
                "evidence_resolution_performed": True,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "eligible_changed": False,
                "fail_closed": True,
            },
        }
        _write(output, payload)
        print(json.dumps({"status": "SUCCESS", "sport": sport, "output": str(output)}, sort_keys=True))
        return 0
    except (FootballPropAutoError, FootballPropRunError, ValueError) as exc:
        payload = {
            "schema_version": "FOOTBALL_PROP_AUTO_RUN_V2",
            "status": "BLOCKED",
            "sport": sport,
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "report": {
                "run_status": "BLOCKED",
                "results": [{
                    "sport": sport,
                    "market": "FOOTBALL_PLAYER_PROPS",
                    "model_p": None,
                    "bet_status": "BLOCKED",
                    "reason": str(exc),
                }],
            },
            "governance": {
                "model_fit_performed": False,
                "evidence_resolution_performed": True,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "eligible_changed": False,
                "fail_closed": True,
            },
        }
        _write(output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
