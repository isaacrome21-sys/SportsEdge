#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json

from sportsedge.dfs.draftkings import DraftKingsClient
from sportsedge.dfs.ownership_evidence import freeze_realized_ownership


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze exact realized ownership from a complete DK standings export."
    )
    parser.add_argument("--standings-csv", required=True)
    parser.add_argument("--contest-id", required=True)
    parser.add_argument("--our-entry-id", required=True)
    parser.add_argument("--slate-lock", required=True, type=_dt)
    parser.add_argument("--expected-field-size", required=True, type=int)
    parser.add_argument("--salary-csv", help="Optional DKSalaries.csv used to map names to DK player IDs")
    parser.add_argument("--output-dir", default="artifacts/dfs/ownership")
    args = parser.parse_args()

    player_map: dict[str, str] | None = None
    if args.salary_csv:
        players = DraftKingsClient().load_salary_csv(args.salary_csv)
        player_map = {player.name: player.player_id for player in players}

    snapshot, output_path = freeze_realized_ownership(
        args.standings_csv,
        output_dir=args.output_dir,
        contest_id=args.contest_id,
        our_entry_id=args.our_entry_id,
        slate_lock=args.slate_lock,
        player_id_by_name=player_map,
        expected_field_size=args.expected_field_size,
    )
    print(json.dumps({**asdict(snapshot), "artifact_path": str(output_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
