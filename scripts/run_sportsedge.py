#!/usr/bin/env python3
"""Run a SportsEdge candidate bundle through the checked-in runtime.

Input is a JSON file containing pipeline times and candidates. This command
never upgrades deployment state: checked-in config/deployments.json remains the
authority and blocked markets stay blocked.
"""
import argparse
import json
from pathlib import Path

from sportsedge.runtime import result_to_dict, run_payload


def main() -> int:
    p = argparse.ArgumentParser(description="Run SportsEdge fail-closed slate candidate bundle")
    p.add_argument("payload", type=Path, help="candidate JSON file")
    p.add_argument("--registry", type=Path, default=Path("config/deployments.json"))
    args = p.parse_args()
    data = json.loads(args.payload.read_text(encoding="utf-8"))
    results = run_payload(data, registry_path=args.registry)
    document = {
        "results": [result_to_dict(x) for x in results],
        "official_bets": sum(x.bet_status == "OFFICIAL_BET" for x in results),
        "passes": sum(x.bet_status == "PASS" for x in results),
        "blocked": sum(x.bet_status == "BLOCKED" for x in results),
    }
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
