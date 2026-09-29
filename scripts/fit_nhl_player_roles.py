#!/usr/bin/env python3
from __future__ import annotations

"""Fit PIT-gated empirical NHL skater role shares from collected official rows."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from sportsedge.sports.nhl.role_history import NHLPlayerGameRoleObservation, fit_empirical_role_shares


def _load_rows(path: Path):
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(NHLPlayerGameRoleObservation(**json.loads(line)))
        except Exception as exc:
            raise ValueError(f"invalid role-history row {line_number}: {exc}") from exc
    return tuple(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit SportsEdge NHL empirical player-role shares")
    parser.add_argument("--role-history", required=True, type=Path)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--cutoff", required=True, help="Timezone-aware target cutoff")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-games", type=int, default=3)
    args = parser.parse_args()

    shares = fit_empirical_role_shares(
        _load_rows(args.role_history),
        cutoff=args.cutoff,
        team_id=args.team_id,
        version=args.version,
        min_games=args.min_games,
    )
    if not shares:
        raise ValueError("no eligible player role shares")
    payload = {
        "authority": "DEVELOPMENT_ROLE_ARTIFACT / NOT Model_P / NOT TRUTH_GATE / NOT OFFICIAL",
        "team_id": args.team_id,
        "cutoff": args.cutoff,
        "version": args.version,
        "min_games": args.min_games,
        "shares": [asdict(row) for row in shares],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
