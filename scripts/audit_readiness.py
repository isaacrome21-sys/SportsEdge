#!/usr/bin/env python3
import argparse
import json

from sportsedge.readiness import audit_readiness


def main() -> int:
    p = argparse.ArgumentParser(description="Audit SportsEdge runtime/deployment readiness")
    p.add_argument("--registry", default="config/deployments.json")
    args = p.parse_args()
    print(json.dumps(audit_readiness(args.registry), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
