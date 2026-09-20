#!/usr/bin/env python3
"""Run frozen CFB offensive prop simulation as a research-only Model_P lane.

This entrypoint deliberately bypasses bettor-facing engine authority. It can emit
research MODEL_CANDIDATE probabilities only after the frozen artifact, frozen
predictive code surface, fresh PIT live features, and a pregame odds snapshot all
validate. It has no evidence/certification/floor promotion path and forcibly
blocks every betting decision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_prop_run_machine import FootballPropRunError, run_football_props
from sportsedge.sports.cfb.prop_bundle import CFBPropBundleError, load_cfb_prop_artifact_bundle
from sportsedge.sports.nfl.prop_code_surface import (
    CFBPropCodeSurfaceError,
    verify_cfb_prop_code_surface,
)

DEFAULT_FREEZE = ROOT / "config/cfb_prop_model_freeze.json"
DEFAULT_BUNDLE = ROOT / "artifacts/football/cfb_prop_artifact_bundle_v1.json"
DEFAULT_FEATURES = ROOT / "artifacts/football/cfb_prop_live_features.json"
DEFAULT_ODDS = ROOT / "artifacts/football/cfb_prop_odds_snapshot.json"
DEFAULT_OUTPUT = ROOT / "artifacts/run_it/cfb_prop_model_candidate.json"


class CFBPropCandidateError(ValueError):
    pass


def _json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBPropCandidateError(code) from exc
    if not isinstance(value, dict):
        raise CFBPropCandidateError(code)
    return value


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _load_frozen_model(freeze_path: Path, bundle_path: Path) -> tuple[dict, str, dict]:
    registry = _json(freeze_path, "CFB_PROP_CANDIDATE_FREEZE_REGISTRY_INVALID")
    if registry.get("sport") != "CFB" or registry.get("status") != "FROZEN":
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_FROZEN_MODEL_REQUIRED")
    if registry.get("promotion_authority") is not False:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_PROMOTION_AUTHORITY_INVALID")
    expected_sha = str(registry.get("artifact_sha256") or "").strip().lower()
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ARTIFACT_SHA_INVALID")
    declared = (ROOT / str(registry.get("artifact_path") or "")).resolve()
    if freeze_path.resolve() == DEFAULT_FREEZE.resolve() and declared != bundle_path.resolve():
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ARTIFACT_BINDING_INVALID")
    artifact = load_cfb_prop_artifact_bundle(root=ROOT, bundle_path=bundle_path)
    fit_sha = str(artifact.get("code_git_sha") or "").strip().lower()
    if fit_sha != str(registry.get("code_git_sha") or "").strip().lower():
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_CODE_SHA_MISMATCH")
    attestation = verify_cfb_prop_code_surface(
        root=ROOT, registry=registry, artifact=artifact
    )
    return artifact, expected_sha, attestation


def _candidateize(report: dict) -> dict:
    candidate_rows = 0
    stale_rows = 0
    for row in report.get("results", []):
        if not isinstance(row, dict):
            continue
        model_p = row.get("model_p")
        genuine = (
            isinstance(model_p, (int, float)) and not isinstance(model_p, bool)
            and isfinite(float(model_p)) and 0.0 <= float(model_p) <= 1.0
        )
        row["official_eligible"] = False
        row["bet_status"] = "BLOCKED"
        row["promotion_authority"] = False
        if genuine and row.get("fair_market_p") is not None and row.get("ev_per_dollar") is not None:
            row["decision_tier"] = "MODEL_CANDIDATE"
            row["model_candidate_status"] = "READY"
            row["reason"] = "CFB_PROP_RESEARCH_ONLY_INDEPENDENT_VALIDATION_REQUIRED"
            candidate_rows += 1
        else:
            row["decision_tier"] = "NO_ACTIONABLE_CANDIDATE"
            row["model_candidate_status"] = "BLOCKED"
            if "STALE" in str(row.get("reason") or ""):
                stale_rows += 1
    report["run_status"] = (
        "MODEL_CANDIDATES_AVAILABLE_OFFICIAL_BLOCKED"
        if candidate_rows else "BLOCKED_NO_FRESH_MODEL_CANDIDATES"
    )
    report.setdefault("summary", {})["model_candidate_rows"] = candidate_rows
    report["summary"]["official_bets"] = 0
    report["summary"]["stale_rows"] = stale_rows
    report["governance"] = {
        **dict(report.get("governance") or {}),
        "research_only": True,
        "promotion_authority": False,
        "official_bets_allowed": False,
        "independent_validation_required": True,
        "engine_surface_changed": False,
        "truth_gate_changed": False,
        "evidence_registry_consumed": False,
        "certification_registry_consumed": False,
        "frozen_edge_floor_can_promote": False,
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-registry", type=Path, default=DEFAULT_FREEZE)
    ap.add_argument("--model-artifact", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--live-features", type=Path, default=DEFAULT_FEATURES)
    ap.add_argument("--odds-snapshot", type=Path, default=DEFAULT_ODDS)
    ap.add_argument("--bookmaker", default="draftkings")
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260909)
    ap.add_argument("--asof")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    current = _utc(args.asof)
    try:
        artifact, artifact_sha, attestation = _load_frozen_model(
            args.freeze_registry, args.model_artifact
        )
        live = _json(args.live_features, "CFB_PROP_CANDIDATE_LIVE_FEATURES_REQUIRED")
        odds = _json(args.odds_snapshot, "CFB_PROP_CANDIDATE_ODDS_SNAPSHOT_REQUIRED")
        report = run_football_props(
            sport="CFB",
            now=current,
            artifact_payload=artifact,
            expected_artifact_sha256=artifact_sha,
            runtime_code_git_sha=str(artifact["code_git_sha"]),
            live_features=live,
            odds_snapshot=odds,
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
            book_key=str(args.bookmaker),
        )
        report = _candidateize(report)
        payload = {
            "schema_version": "CFB_PROP_MODEL_CANDIDATE_RUN_V1",
            "status": "SUCCESS" if report["summary"]["model_candidate_rows"] else "BLOCKED",
            "sport": "CFB",
            "report": report,
            "model_code_attestation": attestation,
            "governance": {
                "research_only": True,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "bettor_facing_engine_surface_unchanged": True,
                "market_prices_can_create_model_p": False,
                "usage_can_be_synthesized": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "status": payload["status"],
            "model_candidate_rows": report["summary"]["model_candidate_rows"],
            "official_bets": 0,
            "output": str(args.output),
        }, sort_keys=True))
        return 0 if payload["status"] == "SUCCESS" else 2
    except (
        CFBPropCandidateError, CFBPropBundleError, CFBPropCodeSurfaceError,
        FootballPropRunError, ValueError,
    ) as exc:
        payload = {
            "schema_version": "CFB_PROP_MODEL_CANDIDATE_RUN_V1",
            "status": "BLOCKED",
            "sport": "CFB",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "report": {
                "run_status": "BLOCKED",
                "results": [{
                    "sport": "CFB", "market": "CFB_PLAYER_PROPS",
                    "model_p": None, "bet_status": "BLOCKED",
                    "official_eligible": False, "reason": str(exc),
                }],
                "summary": {"model_candidate_rows": 0, "official_bets": 0},
            },
            "governance": {
                "research_only": True,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "bettor_facing_engine_surface_unchanged": True,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "BLOCKED", "blocker": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
