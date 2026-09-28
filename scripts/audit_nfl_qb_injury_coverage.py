#!/usr/bin/env python3
"""Fail-closed coverage audit for the preregistered NFL QB/injury mixture lane."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

INJ_REQUIRED = {"season", "week", "position", "report_status"}
ROSTER_REQUIRED = {"season", "week", "position", "team"}
PIT_CANDIDATES = ("date_modified", "report_date", "timestamp")
ID_CANDIDATES = ("gsis_id", "player_id", "full_name")
NA_TOKENS = {"", "na", "nan", "null", "none"}


def _read(paths: list[Path], required: set[str], error: str) -> tuple[list[dict[str, str]], set[str]]:
    rows: list[dict[str, str]] = []
    columns: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            missing = sorted(required - fieldnames)
            if missing:
                raise SystemExit(error + ":" + ",".join(missing))
            columns.update(fieldnames)
            rows.extend(dict(row) for row in reader)
    return rows, columns


def _to_int(value: object) -> int | None:
    text = str(value or "").strip()
    if text.lower() in NA_TOKENS:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _nonnull(value: object) -> bool:
    return str(value or "").strip().lower() not in NA_TOKENS


def _player_column(columns: set[str]) -> str:
    for candidate in ID_CANDIDATES:
        if candidate in columns:
            return candidate
    raise SystemExit("QB_INJURY_COVERAGE_PLAYER_ID_MISSING")


def _key(row: dict[str, str], player_column: str) -> tuple[int | None, int | None, str]:
    return (_to_int(row.get("season")), _to_int(row.get("week")), str(row.get(player_column, "")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--weekly-rosters", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    injuries, injury_columns = _read(
        args.input, INJ_REQUIRED, "QB_INJURY_COVERAGE_REQUIRED_FIELD_MISSING"
    )
    rosters, roster_columns = _read(
        args.weekly_rosters, ROSTER_REQUIRED, "QB_ROSTER_COVERAGE_REQUIRED_FIELD_MISSING"
    )

    injuries = [row for row in injuries if str(row.get("position", "")).upper() == "QB"]
    rosters = [row for row in rosters if str(row.get("position", "")).upper() == "QB"]

    injury_player_column = _player_column(injury_columns)
    roster_player_column = _player_column(roster_columns)

    required_seasons = set(range(2009, 2026))
    observed_injury_seasons = {
        season
        for row in injuries
        if (season := _to_int(row.get("season"))) is not None
    }
    missing_seasons = sorted(required_seasons - observed_injury_seasons)

    timestamp_cols = [candidate for candidate in PIT_CANDIDATES if candidate in injury_columns]
    pit_nonnull = {
        column: sum(1 for row in injuries if _nonnull(row.get(column)))
        for column in timestamp_cols
    }

    injury_keys = {_key(row, injury_player_column) for row in injuries}
    roster_keys = {
        _key(row, roster_player_column)
        for row in rosters
        if (season := _to_int(row.get("season"))) in required_seasons
        and (week := _to_int(row.get("week"))) is not None
        and 1 <= week <= 18
    }

    unmatched = sorted(
        roster_keys - injury_keys,
        key=lambda item: (
            -1 if item[0] is None else item[0],
            -1 if item[1] is None else item[1],
            item[2],
        ),
    )
    by_week: dict[str, int] = {}
    for season, week, _ in unmatched:
        if season is None or week is None:
            continue
        label = f"{season}-{week:02d}"
        by_week[label] = by_week.get(label, 0) + 1

    # Missing injury rows are not proof of health. They remain MISSING.
    fail = bool(missing_seasons or not timestamp_cols or not any(pit_nonnull.values()) or unmatched)
    output = {
        "schema": "NFL_QB_INJURY_COVERAGE_AUDIT_V3",
        "status": "FAIL_CLOSED" if fail else "DENOMINATOR_RECONCILED_NOT_MODEL_ADMITTED",
        "required_seasons": [2009, 2025],
        "missing_injury_seasons": missing_seasons,
        "pit_timestamp_columns_present": timestamp_cols,
        "pit_timestamp_nonnull_rows": pit_nonnull,
        "weekly_roster_qb_keys": len(roster_keys),
        "injury_qb_keys": len(injury_keys),
        "roster_qb_keys_without_injury_row": len(unmatched),
        "unmatched_by_season_week": by_week,
        "missing_state_policy": "ROSTER_QB_WITHOUT_PIT_INJURY_ROW_IS_MISSING_NOT_AVAILABLE",
        "development_validation_scoring_authority": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if fail:
        raise SystemExit("QB_INJURY_COVERAGE_AUDIT_FAILED")


if __name__ == "__main__":
    main()
