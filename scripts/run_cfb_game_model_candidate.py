#!/usr/bin/env python3
"""Research-only CFB game-model candidate runner for ML/spread/total/team total.

Unlike the production AUTO entrypoint, this lane does not require the game-model
freeze registry to be FROZEN. It does require a self-consistent, hash-valid model
artifact whose predictive code-surface hash exactly matches the current checkout.
That allows engineering/research readouts without laundering an unfrozen artifact
into production authority.

Every row is forced to LEAN / MODEL_CANDIDATE / BLOCKED. This script cannot
promote, stake, start an evidence clock, or create OFFICIAL bets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_cfb_auto import discover_cfb_week
from sportsedge.sports.cfb.model_artifact import (
    CFBModelArtifactError,
    cfb_model_code_surface_sha256,
    load_cfb_model_artifact,
)
from sportsedge.sports.cfb.run_machine import CFBRunMachineError, run_it_cfb


class CFBGameCandidateError(ValueError):
    pass


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBGameCandidateError("CFB_GAME_CANDIDATE_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBGameCandidateError("CFB_GAME_CANDIDATE_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBGameCandidateError(code) from exc
    if not isinstance(value, dict):
        raise CFBGameCandidateError(code)
    return value


def _credentials() -> tuple[str, str]:
    cfbd = str(os.environ.get("SPORTSEDGE_CFBD_API_KEY") or os.environ.get("CFBD_API_KEY") or "").strip()
    odds = str(os.environ.get("SPORTSEDGE_ODDS_API_KEY") or os.environ.get("ODDS_API_KEY") or "").strip()
    if not cfbd:
        raise CFBGameCandidateError("CFB_GAME_CANDIDATE_CFBD_API_KEY_REQUIRED")
    if not odds:
        raise CFBGameCandidateError("CFB_GAME_CANDIDATE_ODDS_API_KEY_REQUIRED")
    return cfbd, odds


def _load_candidate(path: Path):
    payload = _json(path, "CFB_GAME_CANDIDATE_ARTIFACT_INVALID")
    runtime_code_sha = cfb_model_code_surface_sha256(ROOT)
    artifact_code_sha = str(payload.get("model_code_sha256") or "").strip().lower()
    if artifact_code_sha != runtime_code_sha:
        raise CFBGameCandidateError("CFB_GAME_CANDIDATE_CODE_SURFACE_MISMATCH")
    try:
        model = load_cfb_model_artifact(
            payload,
            expected_model_code_sha256=runtime_code_sha,
            expected_training_source_sha256=str(payload.get("training_source_sha256") or ""),
        )
    except CFBModelArtifactError as exc:
        raise CFBGameCandidateError(str(exc)) from exc
    return model, payload, runtime_code_sha


def _candidateize(report: dict) -> dict:
    rows = report.get("results")
    if not isinstance(rows, list):
        rows = []
    candidates = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("model_p")
        genuine = False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            p = float(value)
            genuine = isfinite(p) and 0.0 <= p <= 1.0
        row["bet_status"] = "BLOCKED"
        row["official_eligible"] = False
        row["promotion_authority"] = False
        if genuine:
            row["decision_tier"] = "MODEL_CANDIDATE"
            row["presentation_label"] = "LEAN"
            row["reason"] = "CFB_GAME_RESEARCH_ARTIFACT_NOT_PRODUCTION_FROZEN"
            candidates += 1
        else:
            row["decision_tier"] = "NO_ACTIONABLE_CANDIDATE"
            row["presentation_label"] = "NO_PLAY"
    report["run_status"] = (
        "MODEL_CANDIDATES_AVAILABLE_OFFICIAL_BLOCKED"
        if candidates else "BLOCKED_NO_MODEL_CANDIDATES"
    )
    report.setdefault("summary", {})["model_candidate_rows"] = candidates
    report["summary"]["official_bets"] = 0
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-artifact", type=Path, required=True)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--asof")
    ap.add_argument("--bookmaker", action="append", dest="bookmakers")
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260826)
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_game_model_candidate.json"))
    args = ap.parse_args()
    current = _utc(args.asof)
    try:
        model, artifact, runtime_code_sha = _load_candidate(args.model_artifact)
        cfbd, odds = _credentials()
        season = int(args.season if args.season is not None else current.year)
        week = int(args.week) if args.week is not None else discover_cfb_week(
            season=season, now=current, cfbd_api_key=cfbd
        )
        report = run_it_cfb(
            mode="AUTOMATIC",
            season=season,
            week=week,
            model=model,
            now=current,
            cfbd_api_key=cfbd,
            odds_api_key=odds,
            bookmakers=tuple(args.bookmakers or ["draftkings"]),
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
        ).to_dict()
        report = _candidateize(report)
        payload = {
            "schema_version": "CFB_GAME_MODEL_CANDIDATE_RUN_V1",
            "status": "SUCCESS" if report["summary"]["model_candidate_rows"] else "BLOCKED",
            "sport": "CFB",
            "season": season,
            "week": week,
            "artifact_sha256": artifact["artifact_sha256"],
            "model_code_sha256": runtime_code_sha,
            "training_source_sha256": artifact["training_source_sha256"],
            "report": report,
            "governance": {
                "research_only": True,
                "game_model_registry_freeze_required_for_production": True,
                "production_freeze_bypassed": False,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "truth_gate_changed": False,
                "evidence_clock_started": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": payload["status"],
            "model_candidate_rows": report["summary"]["model_candidate_rows"],
            "official_bets": 0,
            "output": str(args.output),
        }, sort_keys=True))
        return 0 if payload["status"] == "SUCCESS" else 2
    except (CFBGameCandidateError, CFBRunMachineError, ValueError) as exc:
        payload = {
            "schema_version": "CFB_GAME_MODEL_CANDIDATE_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "governance": {
                "research_only": True,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "truth_gate_changed": False,
                "evidence_clock_started": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
