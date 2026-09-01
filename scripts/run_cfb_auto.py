#!/usr/bin/env python3
"""Fail-closed automatic CFB entrypoint for the canonical SportsEdge run machine.

The script never trains a model. It requires a prebuilt, hash-bound CFB joint-model
artifact and the existing CFBD/Odds credentials, discovers the next FBS regular-
season week when one is not explicitly supplied, then calls the same AUTOMATIC
library path used by MANUAL/HYBRID parity tests. Objective context is acquired as a
separate sidecar and never substituted for Model_P inputs or promotion evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Callable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.cfb.full_auto import build_cfb_full_auto_slate
from sportsedge.sports.cfb.model_artifact import (
    CFBModelArtifactError,
    cfb_model_code_surface_sha256,
    load_cfb_model_artifact,
)
from sportsedge.sports.cfb.run_machine import run_it_cfb
from sportsedge.sports.cfb.source import CFBGame, fetch_cfbd_games


class CFBAutoError(ValueError):
    pass


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAutoError("CFB_AUTO_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBAutoError("CFB_AUTO_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _dt(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAutoError("CFB_AUTO_GAME_START_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBAutoError("CFB_AUTO_GAME_START_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def discover_cfb_week(
    *,
    season: int,
    now: datetime,
    cfbd_api_key: str,
    game_fetcher: Callable[..., Sequence[CFBGame]] = fetch_cfbd_games,
    max_week: int = 16,
) -> int:
    """Return the earliest regular-season FBS week with a future kickoff."""
    if max_week < 0:
        raise CFBAutoError("CFB_AUTO_MAX_WEEK_INVALID")
    candidates: list[tuple[datetime, int]] = []
    for week in range(0, int(max_week) + 1):
        games = game_fetcher(season=int(season), week=week, cfbd_api_key=cfbd_api_key)
        for game in games:
            start = _dt(game.start_ts)
            if start > now:
                candidates.append((start, int(game.week)))
    if not candidates:
        raise CFBAutoError("CFB_AUTO_NO_FUTURE_FBS_WEEK")
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][1]


def _credentials() -> tuple[str, str]:
    cfbd = str(os.environ.get("SPORTSEDGE_CFBD_API_KEY") or os.environ.get("CFBD_API_KEY") or "").strip()
    odds = str(os.environ.get("SPORTSEDGE_ODDS_API_KEY") or os.environ.get("ODDS_API_KEY") or "").strip()
    if not cfbd:
        raise CFBAutoError("CFB_AUTO_CFBD_API_KEY_REQUIRED")
    if not odds:
        raise CFBAutoError("CFB_AUTO_ODDS_API_KEY_REQUIRED")
    return cfbd, odds


def _model(path: Path, *, repo_root: Path):
    if not path.is_file():
        raise CFBAutoError("CFB_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBAutoError("CFB_AUTO_MODEL_ARTIFACT_UNREADABLE") from exc
    code_sha = cfb_model_code_surface_sha256(repo_root)
    expected_source = str(os.environ.get("SPORTSEDGE_CFB_TRAINING_SOURCE_SHA256") or "").strip() or None
    try:
        model = load_cfb_model_artifact(
            payload,
            expected_model_code_sha256=code_sha,
            expected_training_source_sha256=expected_source,
        )
    except CFBModelArtifactError as exc:
        raise CFBAutoError(str(exc)) from exc
    return model, payload


def _objective_context(*, current: datetime, season: int, cfbd_key: str) -> tuple[str, dict | None, str | None]:
    """Acquire optional objective context without turning a sidecar failure into a slate-wide model failure."""
    try:
        payload = build_cfb_full_auto_slate(
            as_of=current,
            cfbd_api_key=cfbd_key,
            season=season,
            mode="AUTO",
            min_lead_minutes=0,
            horizon_minutes=7 * 24 * 60,
        )
        return "AVAILABLE", payload, None
    except Exception as exc:
        return "SOURCE_FAILED", None, f"{type(exc).__name__}:{exc}"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--asof")
    parser.add_argument("--model-artifact", type=Path, default=Path("models/cfb_joint_v1.json"))
    parser.add_argument("--bookmaker", action="append", dest="bookmakers")
    parser.add_argument("--n-paths", type=int, default=20000)
    parser.add_argument("--root-seed", type=int, default=20260826)
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_card.json"))
    args = parser.parse_args()

    root = _REPO_ROOT
    current = _utc(args.asof)
    try:
        cfbd_key, odds_key = _credentials()
        model, artifact = _model(args.model_artifact, repo_root=root)
        season = int(args.season if args.season is not None else current.year)
        week = int(args.week) if args.week is not None else discover_cfb_week(
            season=season,
            now=current,
            cfbd_api_key=cfbd_key,
        )
        context_status, objective_context, context_error = _objective_context(
            current=current,
            season=season,
            cfbd_key=cfbd_key,
        )
        report = run_it_cfb(
            mode="AUTOMATIC",
            season=season,
            week=week,
            model=model,
            now=current,
            cfbd_api_key=cfbd_key,
            odds_api_key=odds_key,
            bookmakers=tuple(args.bookmakers or ["draftkings"]),
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
        )
        payload = {
            "schema_version": "CFB_AUTO_RUN_V1",
            "status": "SUCCESS",
            "season": season,
            "week": week,
            "model_artifact_sha256": artifact["artifact_sha256"],
            "model_code_sha256": artifact["model_code_sha256"],
            "training_source_sha256": artifact["training_source_sha256"],
            "objective_context_status": context_status,
            "objective_context_error": context_error,
            "objective_context": objective_context,
            "report": report.to_dict(),
            "governance": {
                "model_fit_performed": False,
                "objective_context_is_model_p": False,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True,
                "context_failure_is_scoped": True,
            },
        }
        _write(args.output, payload)
        print(json.dumps({
            "status": "SUCCESS",
            "season": season,
            "week": week,
            "run_status": report.run_status,
            "objective_context_status": context_status,
            "output": str(args.output),
        }, sort_keys=True))
        return 0
    except (CFBAutoError, ValueError) as exc:
        payload = {
            "schema_version": "CFB_AUTO_RUN_V1",
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
