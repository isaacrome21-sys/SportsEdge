#!/usr/bin/env python3
from pathlib import Path

from direct_threshold_loader_v0_3 import load_all_direct_threshold_artifacts
from deployment_parity_v0_3 import market_deployment_status


def main():
    root = Path(__file__).resolve().parent
    loaded = load_all_direct_threshold_artifacts(root)
    caps = {
        "registry_schema_version": "1.6",
        **loaded["capability_attestation"],
    }

    import json
    registry = json.loads((root / "registry_v1_6.json").read_text())

    rbi = market_deployment_status(registry, "rbi", root, caps)
    runs = market_deployment_status(registry, "runs", root, caps)
    assert rbi["status"] == "PASS", rbi
    assert runs["status"] == "PASS_CAUTION", runs

    assert loaded["loaded"]["rbi"]["validation_hash"] == "0debe7836f983e2711a347ba76be3ce1ca5c36a5b76421d36575b84bbbc8463b"
    assert loaded["loaded"]["runs"]["validation_hash"] == "25a83e319ba6682cb1c60d9c4e5d9f758feffc3f3bc19a16ca0fb21deb2d03bf"
    assert len(loaded["loaded"]["rbi"]["artifact"]["models"]) == 6
    assert len(loaded["loaded"]["runs"]["artifact"]["models"]) == 6
    print("ALL DIRECT THRESHOLD LOADER V0.3 TESTS PASS")


if __name__ == "__main__":
    main()
