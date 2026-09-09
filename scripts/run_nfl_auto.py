#!/usr/bin/env python3
"""Executable fail-closed NFL M2 RUN IT lane.

No model fitting occurs here.  A frozen, Git-SHA-bound NFL M2 artifact is required.
The operator may supply both live features and an observed odds snapshot (MANUAL),
one of them (HYBRID), or neither (AUTOMATIC).  Missing inputs are acquired through
the same reusable feature-builder and odds-source contracts used by evidence/CLV
workflows.  Every mode then enters ``sportsedge.sports.nfl.run_machine``.

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

from sportsedge.sports.nfl.live_features import build_nfl_live_feature_payload
from sportsedge.sports.nfl.odds_source import fetch_nfl_odds
from sportsedge.sports.nfl.run_machine import (
    DEFAULT_FEATURE_TTL_SECONDS,
    DEFAULT_QUOTE_TTL_SECONDS,
    NFLRunMachineError,
    run_it_nfl,
)

_KEYS = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)


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
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="AUTO_SELECT", choices=("AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"))
    parser.add_argument("--asof")
    parser.add_argument("--model-artifact", type=Path, default=Path("artifacts/football/nfl_m2_model.json"))
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
        artifact = _json(args.model_artifact, "NFL_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
        runtime_sha = _runtime_git_sha(args.runtime_code_git_sha)
        supplied_features = _operator_payload(args.live_features, "NFL_AUTO_LIVE_FEATURES_UNREADABLE")
        supplied_odds = _operator_payload(args.odds_snapshot, "NFL_AUTO_ODDS_SNAPSHOT_UNREADABLE")

        # A real network quote cannot be replayed at a caller-selected historical
        # timestamp.  If odds are not supplied, an explicit --asof would make the
        # observation time ambiguous, so fail closed rather than fabricate it.
        needs_network_odds = supplied_odds is None and str(args.mode).upper() in ("AUTO_SELECT", "HYBRID", "AUTOMATIC")
        if needs_network_odds and args.asof is not None:
            raise NFLAutoError("NFL_AUTO_NETWORK_ODDS_WITH_EXPLICIT_ASOF_PROHIBITED")

        def build_features() -> dict[str, Any]:
            return build_nfl_live_feature_payload(
                schedule_file=args.schedule_file,
                pbp_dir=args.pbp_dir,
                participation_dir=args.participation_dir,
                depth_dir=args.depth_dir,
                stadium_file=args.stadium_file,
                asof=current,
                start_season=int(args.start_season),
                current_season=int(args.current_season if args.current_season is not None else current.year),
                horizon_minutes=int(args.horizon_minutes),
                min_lead_minutes=int(args.min_lead_minutes),
            )

        def fetch_odds() -> dict[str, Any]:
            # ``observed_at`` is the acquisition-request timestamp, captured before
            # bytes are requested.  It is never synthesized for operator snapshots.
            observed_at = datetime.now(timezone.utc)
            result = fetch_nfl_odds(_odds_keys())
            payload = result.value
            if not isinstance(payload, list):
                raise NFLAutoError("NFL_AUTO_ODDS_PROVIDER_PAYLOAD_INVALID")
            return {
                "schema_version": 1,
                "sport": "nfl",
                "source": "the-odds-api",
                "observed_at": observed_at.isoformat(),
                "events": payload,
                "key_slot": result.key_slot,
                "prior_key_failures": len(result.failures),
            }

        # For live automatic acquisition, refresh execution time immediately
        # before the canonical call.  Operator/replay runs keep their requested asof.
        execution_now = datetime.now(timezone.utc) if args.asof is None else current
        report = run_it_nfl(
            mode=str(args.mode).upper(),
            model_artifact=artifact,
            runtime_code_git_sha=runtime_sha,
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
            "schema_version": "NFL_AUTO_RUN_V1",
            "status": "SUCCESS",
            "report": report.to_dict(),
            "governance": {
                "model_fit_performed": False,
                "market_prices_are_model_features": False,
                "props_promoted": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps({
            "status": "SUCCESS",
            "mode": report.mode,
            "run_status": report.run_status,
            "priced": report.summary["priced"],
            "official_bets": report.summary["official_bets"],
            "output": str(args.output),
        }, sort_keys=True))
        return 0
    except (NFLAutoError, NFLRunMachineError, ValueError) as exc:
        payload = {
            "schema_version": "NFL_AUTO_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "governance": {
                "model_fit_performed": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
