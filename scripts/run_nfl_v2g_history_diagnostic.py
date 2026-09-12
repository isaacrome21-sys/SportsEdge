#!/usr/bin/env python3
"""Research-only NFL V2G historical diagnostic input builder.

Historical 2016-2025 data are reused research history, not a final holdout. This
runner prepares manifest-bound possession-event rows only; sportsbook market
columns are deliberately excluded from the projected schedule contract.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.m2_v2g_candidate import build_nfl_v2g_game_event_rows

PBP_FIELDS = {"game_id", "drive", "posteam", "touchdown", "td_team", "play_type", "field_goal_result"}
SCHEDULE_FIELDS = {"game_id", "season", "week", "game_type", "home_team", "away_team", "home_score", "away_score"}
FORBIDDEN_MARKET_FIELDS = {
    "spread_line", "total_line", "moneyline", "home_moneyline", "away_moneyline",
    "home_spread_odds", "away_spread_odds", "over_odds", "under_odds",
    "closing_spread", "closing_total",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _read(path: Path, required: set[str]) -> list[dict[str, str]]:
    with _open(path) as handle:
        reader = csv.DictReader(handle)
        names = set(reader.fieldnames or ())
        missing = required - names
        if missing:
            raise ValueError(f"NFL_V2G_REQUIRED_SOURCE_FIELDS_MISSING:{path}:{','.join(sorted(missing))}")
        return [{field: row.get(field, "") for field in required} for row in reader]


def _assert_market_blind(rows: list[dict]) -> None:
    for index, row in enumerate(rows):
        leaked = sorted(FORBIDDEN_MARKET_FIELDS.intersection(row))
        if leaked:
            raise ValueError(f"NFL_V2G_DIAGNOSTIC_MARKET_FIELD_LEAK:{index}:{','.join(leaked)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--pbp", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    schedule = _read(args.schedule, SCHEDULE_FIELDS)
    pbp: list[dict[str, str]] = []
    for path in args.pbp:
        pbp.extend(_read(path, PBP_FIELDS))

    rows = build_nfl_v2g_game_event_rows(schedule, pbp)
    _assert_market_blind(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": "SPORTSEDGE_NFL_V2G_DIAGNOSTIC_INPUT_V1",
        "status": "RESEARCH_DIAGNOSTIC_ONLY",
        "historical_evidence_integrity": "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT",
        "market_blind_input_contract": True,
        "forbidden_market_fields": sorted(FORBIDDEN_MARKET_FIELDS),
        "promotion_authority": False,
        "production_model_changed": False,
        "market_eligibility_changed": False,
        "official_status_granted": False,
        "nfl_props": "NO_ENGINE",
        "required_schedule_fields": sorted(SCHEDULE_FIELDS),
        "required_pbp_fields": sorted(PBP_FIELDS),
        "schedule": {"path": str(args.schedule), "sha256": _sha256(args.schedule)},
        "pbp": [{"path": str(path), "sha256": _sha256(path)} for path in args.pbp],
        "event_rows": len(rows),
        "event_rows_sha256": _sha256(args.output),
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
