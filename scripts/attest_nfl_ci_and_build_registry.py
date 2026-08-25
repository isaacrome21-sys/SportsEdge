#!/usr/bin/env python3
"""Externally attest a successful NFL evidence run and rebuild its registry.

This script must run in a separate workflow from the evidence producer. It does
not accept a free-form CI boolean; it requires the upstream workflow metadata
plus the downloaded, hash-bound artifact bundle and verifies both before using
``ci_attested=True``.

Forward CLV is deliberately *not* accepted through this CI-attestation path.
A standalone CLV summary, even when internally consistent and code-SHA bound,
is not proof that the underlying forward observations were authentically
captured. Promotion-grade CLV requires its own external workflow attestation
before it may be supplied to a deployment registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.core.validation.nfl_ci_attestation import verify_nfl_pre_ci_bundle


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--workflow-conclusion", required=True)
    parser.add_argument("--workflow-head-sha", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--market-surface", type=Path, default=Path("config/football_market_surface.json"))
    # Retained temporarily as an explicit fail-closed compatibility boundary so
    # old callers get a stable error rather than silently using unattested CLV.
    parser.add_argument("--clv-evidence", type=Path)
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_ci_attested_registry.json"))
    args = parser.parse_args()

    if args.clv_evidence is not None:
        raise SystemExit("NFL_CLV_EXTERNAL_ATTESTATION_REQUIRED")

    attestation = verify_nfl_pre_ci_bundle(
        args.bundle_dir,
        workflow_name=args.workflow_name,
        workflow_conclusion=args.workflow_conclusion,
        workflow_head_sha=args.workflow_head_sha,
        workflow_run_id=args.workflow_run_id,
    )

    math_payload = _json(args.bundle_dir / "nfl_simulator_profile.json")
    math_artifact = math_payload.get("math_artifact", math_payload)
    history = _json(args.bundle_dir / "nfl_production_validation.json")
    surface = _json(args.market_surface)
    if "NFL" not in {str(s).upper() for s in surface.get("sports", [])}:
        raise SystemExit("NFL_MARKET_SURFACE_NOT_DECLARED")
    markets = [
        str(row["market"])
        for row in surface.get("markets", [])
        if isinstance(row, dict) and row.get("market")
    ]
    if not markets:
        raise SystemExit("NFL_MARKET_SURFACE_EMPTY")

    registry = build_nfl_promotion_registry(
        math_artifact,
        history,
        declared_markets=markets,
        ci_attested=True,
        ci_attestation=attestation,
        clv_evidence=None,
    )
    registry["ci_attestation_state"] = "ATTESTED_BY_SEPARATE_WORKFLOW"
    registry["clv_attestation_state"] = "EXTERNAL_ATTESTATION_REQUIRED"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "git_sha": registry["code_git_sha"],
        "source_manifest_sha256": registry["source_manifest_sha256"],
        "deployed_markets": registry["deployed_markets"],
        "ci_attestation": registry["ci_attestation"],
        "clv_attestation_state": registry["clv_attestation_state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
