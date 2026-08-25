#!/usr/bin/env python3
"""Build the final NFL registry from two independent successful workflow bundles.

Deployment-grade evidence requires BOTH:
1. the existing externally verified production-M2/CI evidence bundle; and
2. a separately scheduled main-branch forward-CLV capture bundle.

The two workflows must bind the same exact production code SHA.  This script
never accepts a free-form boolean or unattested CLV summary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sportsedge.core.promotion.nfl_external_deployment import build_externally_attested_nfl_registry
from sportsedge.core.validation.nfl_ci_attestation import verify_nfl_pre_ci_bundle
from sportsedge.core.validation.nfl_forward_clv_attestation import verify_nfl_forward_clv_bundle


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"NFL_EXTERNAL_ATTESTATION_JSON_INVALID:{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"NFL_EXTERNAL_ATTESTATION_JSON_NOT_OBJECT:{path}")
    return payload


def _declared_markets(path: Path) -> list[str]:
    surface = _json(path)
    if "NFL" not in {str(s).upper() for s in surface.get("sports", [])}:
        raise ValueError("NFL_MARKET_SURFACE_NOT_DECLARED")
    markets: list[str] = []
    seen: set[str] = set()
    for row in surface.get("markets", []):
        if not isinstance(row, dict):
            continue
        market = str(row.get("market") or "").strip().lower()
        if market and market not in seen:
            seen.add(market)
            markets.append(market)
    if not markets:
        raise ValueError("NFL_MARKET_SURFACE_EMPTY")
    return markets


def build_registry_from_bundles(
    *,
    ci_bundle_dir: Path,
    ci_workflow_name: str,
    ci_workflow_conclusion: str,
    ci_workflow_head_sha: str,
    ci_workflow_run_id: int,
    forward_bundle_dir: Path,
    forward_workflow_name: str,
    forward_workflow_conclusion: str,
    forward_workflow_event: str,
    forward_workflow_head_branch: str,
    forward_workflow_head_sha: str,
    forward_workflow_run_id: int,
    market_surface: Path,
) -> dict[str, Any]:
    if str(ci_workflow_head_sha).strip().lower() != str(forward_workflow_head_sha).strip().lower():
        raise ValueError("NFL_EXTERNAL_ATTESTATION_CODE_SHA_MISMATCH")

    ci_attestation = verify_nfl_pre_ci_bundle(
        ci_bundle_dir,
        workflow_name=ci_workflow_name,
        workflow_conclusion=ci_workflow_conclusion,
        workflow_head_sha=ci_workflow_head_sha,
        workflow_run_id=ci_workflow_run_id,
    )
    clv_attestation = verify_nfl_forward_clv_bundle(
        forward_bundle_dir,
        workflow_name=forward_workflow_name,
        workflow_conclusion=forward_workflow_conclusion,
        workflow_event=forward_workflow_event,
        workflow_head_branch=forward_workflow_head_branch,
        workflow_head_sha=forward_workflow_head_sha,
        workflow_run_id=forward_workflow_run_id,
    )
    if ci_attestation["git_sha"] != clv_attestation["git_sha"]:
        raise ValueError("NFL_EXTERNAL_ATTESTATION_CODE_SHA_MISMATCH")

    math_payload = _json(ci_bundle_dir / "nfl_simulator_profile.json")
    math_artifact = math_payload.get("math_artifact", math_payload)
    if not isinstance(math_artifact, dict):
        raise ValueError("NFL_EXTERNAL_ATTESTATION_MATH_ARTIFACT_INVALID")
    historical_evidence = _json(ci_bundle_dir / "nfl_production_validation.json")
    clv_evidence = _json(forward_bundle_dir / "nfl_clv_evidence.json")

    return build_externally_attested_nfl_registry(
        math_artifact,
        historical_evidence,
        declared_markets=_declared_markets(market_surface),
        ci_attestation=ci_attestation,
        clv_evidence=clv_evidence,
        clv_attestation=clv_attestation,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ci-bundle-dir", type=Path, required=True)
    p.add_argument("--ci-workflow-name", required=True)
    p.add_argument("--ci-workflow-conclusion", required=True)
    p.add_argument("--ci-workflow-head-sha", required=True)
    p.add_argument("--ci-workflow-run-id", type=int, required=True)
    p.add_argument("--forward-bundle-dir", type=Path, required=True)
    p.add_argument("--forward-workflow-name", required=True)
    p.add_argument("--forward-workflow-conclusion", required=True)
    p.add_argument("--forward-workflow-event", required=True)
    p.add_argument("--forward-workflow-head-branch", required=True)
    p.add_argument("--forward-workflow-head-sha", required=True)
    p.add_argument("--forward-workflow-run-id", type=int, required=True)
    p.add_argument("--market-surface", type=Path, default=Path("config/football_market_surface.json"))
    p.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_externally_attested_registry.json"))
    args = p.parse_args()

    registry = build_registry_from_bundles(
        ci_bundle_dir=args.ci_bundle_dir,
        ci_workflow_name=args.ci_workflow_name,
        ci_workflow_conclusion=args.ci_workflow_conclusion,
        ci_workflow_head_sha=args.ci_workflow_head_sha,
        ci_workflow_run_id=args.ci_workflow_run_id,
        forward_bundle_dir=args.forward_bundle_dir,
        forward_workflow_name=args.forward_workflow_name,
        forward_workflow_conclusion=args.forward_workflow_conclusion,
        forward_workflow_event=args.forward_workflow_event,
        forward_workflow_head_branch=args.forward_workflow_head_branch,
        forward_workflow_head_sha=args.forward_workflow_head_sha,
        forward_workflow_run_id=args.forward_workflow_run_id,
        market_surface=args.market_surface,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "code_git_sha": registry["code_git_sha"],
        "deployed_markets": registry["deployed_markets"],
        "ci_workflow_run_id": registry["ci_attestation"]["workflow_run_id"],
        "forward_clv_workflow_run_id": registry["clv_attestation"]["workflow_run_id"],
        "clv_attestation_state": registry["clv_attestation_state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
