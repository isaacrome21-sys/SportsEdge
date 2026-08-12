#!/usr/bin/env python3
"""Source-bounded successor to cutoff-correct core game-market rebuild v3.

This preserves v3 model math/tolerances. The only change is provenance plumbing:
every schedule response/cache row is checked against the exact requested start/end
interval before any Final row can enter feature construction.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import scripts.rebuild_game_nrfi_models_v3 as base
from sportsedge.historical_cutoff import suspended_or_resumed_reason
from sportsedge.source_range import partition_schedule_games


def fetch_games_strict(cache_dir: Path):
    cache_dir.mkdir(parents=True, exist_ok=True)
    by_pk: dict[int, dict] = {}
    excluded_by_key: dict[tuple, dict] = {}

    def exclude(row: dict):
        key = (
            row.get("game_pk"), row.get("official_date"), row.get("reason_code"),
            row.get("requested_start"), row.get("requested_end"),
        )
        excluded_by_key[key] = row

    for year in base.YEARS:
        for start, end in base.ranges(year):
            path = cache_dir / f"schedule_{start}_{end}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = base.core.get_json(
                    "/api/v1/schedule",
                    {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "linescore,team"},
                )
                path.write_text(json.dumps(data), encoding="utf-8")

            accepted, violations = partition_schedule_games(data, start=start, end=end)
            for row in violations:
                exclude(row)

            for game in accepted:
                if str(game.get("gameType")) != "R":
                    continue
                if (game.get("status") or {}).get("abstractGameState") != "Final":
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
                linescore = game.get("linescore") or {}
                teams = game.get("teams") or {}
                try:
                    home_runs = int(((linescore.get("teams") or {}).get("home") or {})["runs"])
                    away_runs = int(((linescore.get("teams") or {}).get("away") or {})["runs"])
                    home_id = int(((teams.get("home") or {}).get("team") or {})["id"])
                    away_id = int(((teams.get("away") or {}).get("team") or {})["id"])
                    d = date.fromisoformat(official)
                except Exception:
                    exclude({"game_pk": pk, "official_date": official, "reason_code": "FINAL_GAME_FIELDS_INVALID"})
                    continue
                first = next((x for x in (linescore.get("innings") or []) if int(x.get("num") or 0) == 1), None)
                if not first:
                    exclude({"game_pk": pk, "official_date": official, "reason_code": "FIRST_INNING_RESULT_MISSING"})
                    continue
                try:
                    away_fi = int((first.get("away") or {}).get("runs", 0))
                    home_fi = int((first.get("home") or {}).get("runs", 0))
                except Exception:
                    exclude({"game_pk": pk, "official_date": official, "reason_code": "FIRST_INNING_RESULT_INVALID"})
                    continue
                by_pk[pk] = {
                    "game_pk": pk,
                    "officialDate": d.isoformat(),
                    "date": d.isoformat(),
                    "year": d.year,
                    "month": d.month,
                    "away_id": away_id,
                    "home_id": home_id,
                    "away_runs": away_runs,
                    "home_runs": home_runs,
                    "away_fi": away_fi,
                    "home_fi": home_fi,
                }

    games = sorted(by_pk.values(), key=lambda x: (x["officialDate"], x["game_pk"]))
    excluded = sorted(excluded_by_key.values(), key=lambda x: (
        x.get("official_date") or "", x.get("game_pk") or 0, x.get("reason_code") or "",
        x.get("requested_start") or "", x.get("requested_end") or "",
    ))
    return games, excluded


def main():
    captured: dict[str, object] = {}

    def capture(cache_dir: Path):
        games, excluded = fetch_games_strict(cache_dir)
        captured["games"] = games
        captured["excluded"] = excluded
        return games, excluded

    base.fetch_games_cutoff = capture
    rc = base.main()

    path = Path("artifacts/core_game_markets_validation_v3.json")
    if path.exists():
        validation = json.loads(path.read_text(encoding="utf-8"))
        games = captured.get("games") or []
        excluded = captured.get("excluded") or []
        scored_dates = [g["officialDate"] for g in games if int(g["year"]) == 2026]
        validation["schema_version"] = "core_game_markets_rebuild_v3_1_cutoff_correct_source_bounded"
        validation["source_range_policy"] = "EVERY_RESPONSE_AND_CACHE_ROW_MUST_MATCH_REQUESTED_INTERVAL"
        validation["source_range_violation_count"] = sum(1 for x in excluded if x.get("reason_code") == "SOURCE_RANGE_VIOLATION")
        validation["observed_2026_scored_date_min"] = min(scored_dates) if scored_dates else None
        validation["observed_2026_scored_date_max"] = max(scored_dates) if scored_dates else None
        validation["declared_2026_holdout_end"] = "2026-08-10"
        validation["source_bound_assertion_pass"] = bool(scored_dates) and max(scored_dates) <= "2026-08-10"
        path.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not validation["source_bound_assertion_pass"]:
            return 3
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
