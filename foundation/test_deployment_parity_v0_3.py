#!/usr/bin/env python3
import hashlib
import json
import tempfile
from pathlib import Path

from deployment_parity_v0_3 import audit_deployment_parity, market_deployment_status


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        blob = b"validated-direct-threshold-artifact"
        good_hash = hashlib.sha256(blob).hexdigest()
        (root / "sportsedge_rbi_direct_v1.joblib").write_bytes(blob)

        registry = {
            "schema_version": "1.6",
            "markets": {
                "rbi": {
                    "status": "PASS",
                    "official_eligible": True,
                    "artifact": {
                        "path": "sportsedge_rbi_direct_v1.joblib",
                        "artifact_hash": good_hash,
                    },
                },
                "runs": {
                    "status": "PASS_CAUTION",
                    "official_eligible": True,
                    "artifact": {
                        "path": "sportsedge_runs_direct_v1.joblib",
                        "artifact_hash": "0" * 64,
                    },
                },
                "team total": {
                    "status": "PASS_GATED",
                    "official_eligible": True,
                    "scope": {
                        "allowed_lines": ["5.5+"],
                        "caution_lines": ["4.5"],
                        "blocked_lines": ["2.5", "3.5"],
                    },
                },
                "hits": {
                    "status": "PASS_CAUTION",
                    "official_eligible": True,
                    "deployment_requirement": "shared game-effect sampling (sigma=0.20) must be active",
                },
                "pitcher earned runs": {
                    "status": "BLOCKED",
                    "official_eligible": False,
                },
            },
        }

        r = market_deployment_status(registry, "rbi", root)
        assert r["status"] == "PASS", r

        r = market_deployment_status(registry, "runs", root)
        assert r["status"] == "BLOCKED_DEPLOYMENT_PARITY" and r["reason"] == "MISSING_REQUIRED_ARTIFACT", r

        r = market_deployment_status(registry, "team total", root, {}, 3.5)
        assert r["status"] == "BLOCKED" and r["reason"] == "REGISTRY_SCOPE_BLOCKED_LINE", r

        r = market_deployment_status(registry, "team total", root, {"team_total_line_policy_v1": True}, 4.5)
        assert r["status"] == "PASS_CAUTION", r

        r = market_deployment_status(registry, "team total", root, {"team_total_line_policy_v1": True}, 5.5)
        assert r["status"] == "PASS", r

        r = market_deployment_status(registry, "hits", root)
        assert r["status"] == "BLOCKED_DEPLOYMENT_PARITY", r
        r = market_deployment_status(registry, "hits", root, {"shared_game_effect_sigma_0_20": True})
        assert r["status"] == "PASS_CAUTION", r

        r = market_deployment_status(registry, "pitcher earned runs", root)
        assert r["status"] == "BLOCKED" and r["reason"] == "REGISTRY_NOT_OFFICIAL_ELIGIBLE", r

        report = audit_deployment_parity(registry, root, {"team_total_line_policy_v1": True})
        assert report["overall_status"] == "FAIL_CLOSED" and report["blocked_count"] >= 3, report

    print("ALL DEPLOYMENT PARITY V0.3 TESTS PASS")


if __name__ == "__main__":
    main()
