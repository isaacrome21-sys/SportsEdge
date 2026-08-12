#!/usr/bin/env python3
"""Source-bounded successor to pitcher BB v4.

Model features, math, thresholds, tolerances, and 2025 calibration are unchanged.
Only source provenance is tightened so out-of-request schedule/cache rows can never
enter historical state or the declared 2026 holdout.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import scripts.rebuild_pitcher_bb_v4 as base
from sportsedge.historical_cutoff import suspended_or_resumed_reason
from sportsedge.source_range import partition_schedule_games


def fetch_schedule_strict(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    by: dict[int, dict] = {}
    excluded_by_key: dict[tuple, dict] = {}

    def exclude(row: dict):
        key = (
            row.get("game_pk"), row.get("official_date"), row.get("reason_code"),
            row.get("requested_start"), row.get("requested_end"),
        )
        excluded_by_key[key] = row

    for year in base.YEARS:
        for start, end in base.month_ranges(year):
            path = cache / f"schedule_{start}_{end}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = base.old.get(
                    "/api/v1/schedule",
                    {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "team"},
                )
                path.write_text(json.dumps(data), encoding="utf-8")

            accepted, violations = partition_schedule_games(data, start=start, end=end)
            for row in violations:
                exclude(row)

            for game in accepted:
                if game.get("gameType") != "R" or (game.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                pk = int(game.get("gamePk") or 0)
                reason = suspended_or_resumed_reason(game)
                if reason:
                    exclude({"game_pk": pk, "official_date": game.get("officialDate"), "reason_code": reason})
                    continue
                official = game.get("officialDate")
                if not isinstance(official, str) or not official:
                    exclude({"game_pk": pk, "official_date": None, "reason_code": "OFFICIAL_DATE_INVALID_OR_MISSING"})
                    continue
                try:
                    dt = date.fromisoformat(official)
                    away_id = int(game["teams"]["away"]["team"]["id"])
                    home_id = int(game["teams"]["home"]["team"]["id"])
                except Exception:
                    exclude({"game_pk": pk, "official_date": official, "reason_code": "SCHEDULE_FIELDS_INVALID"})
                    continue
                by[pk] = {
                    "game_pk": pk,
                    "officialDate": dt.isoformat(),
                    "date": dt.isoformat(),
                    "year": dt.year,
                    "away_id": away_id,
                    "home_id": home_id,
                }

    games = sorted(by.values(), key=lambda x: (x["officialDate"], x["game_pk"]))
    excluded = sorted(excluded_by_key.values(), key=lambda x: (
        x.get("official_date") or "", x.get("game_pk") or 0, x.get("reason_code") or "",
        x.get("requested_start") or "", x.get("requested_end") or "",
    ))
    return games, excluded


def main():
    captured: dict[str, object] = {}

    def capture(cache: Path):
        games, excluded = fetch_schedule_strict(cache)
        captured["games"] = games
        captured["excluded"] = excluded
        return games, excluded

    base.fetch_schedule_cutoff = capture
    rc = base.main()

    path = Path("artifacts/pitcher_bb_v4_validation.json")
    if path.exists():
        validation = json.loads(path.read_text(encoding="utf-8"))
        games = captured.get("games") or []
        excluded = captured.get("excluded") or []
        dates = [g["officialDate"] for g in games if int(g["year"]) == 2026]
        validation["version"] = "PITCHER_BB_V4_1_CUTOFF_CORRECT_SOURCE_BOUNDED"
        validation["source_range_policy"] = "EVERY_RESPONSE_AND_CACHE_ROW_MUST_MATCH_REQUESTED_INTERVAL"
        validation["source_range_violation_count"] = sum(1 for x in excluded if x.get("reason_code") == "SOURCE_RANGE_VIOLATION")
        validation["observed_2026_schedule_date_min"] = min(dates) if dates else None
        validation["observed_2026_schedule_date_max"] = max(dates) if dates else None
        validation["declared_2026_holdout_end"] = "2026-08-10"
        validation["source_bound_assertion_pass"] = bool(dates) and max(dates) <= "2026-08-10"
        path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not validation["source_bound_assertion_pass"]:
            return 3
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
