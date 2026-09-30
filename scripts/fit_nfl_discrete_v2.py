#!/usr/bin/env python3
"""Rebuild config/nfl_discrete_v2_freeze.json from the 2021-2024 snapshot."""
from sportsedge.sports.nfl.discrete_v2_fit import write_freeze


def main() -> None:
    payload = write_freeze()
    print(payload["artifact_sha256"])
    print(payload["fit_window"]["source_sha256"])
    print(payload["shape"]["margin_lifts"])


if __name__ == "__main__":
    main()
