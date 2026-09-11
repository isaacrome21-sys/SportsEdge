#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sportsedge.mlb_v7_statsapi_history import build_shard_report, detailed_status_by_game, write_json, write_jsonl
from sportsedge.mlb_v7_travel_history import _get_json, extract_timecodes, historical_snapshot_url, normalize_final_game, schedule_games, schedule_url, timestamps_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire one fail-closed MLB StatsAPI historical travel shard.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end or (end - start).days > 31:
        raise SystemExit("MLB_V7_HISTORY_SHARD_WINDOW_INVALID")

    root = Path(args.output_root)
    failures: list[dict[str, object]] = []
    evidence_files: list[dict[str, str]] = []
    sched_url = schedule_url(start.isoformat(), end.isoformat())
    schedule_payload = _get_json(sched_url)
    schedule_rel = Path("raw/schedule.json")
    schedule_sha = write_json(root / schedule_rel, schedule_payload)
    evidence_files.append({"path": schedule_rel.as_posix(), "sha256": schedule_sha})

    games = schedule_games(schedule_payload)
    detailed = detailed_status_by_game(schedule_payload)
    for game in games:
        game["detailed_status"] = detailed.get(int(game["game_id"]), "")

    normalized_rows = []
    for game in games:
        if game["status"] != "Final":
            continue
        game_id = int(game["game_id"])
        try:
            timestamps_payload = _get_json(timestamps_url(game_id))
            timecodes = extract_timecodes(timestamps_payload)
            final_timecode = timecodes[-1]
            final_snapshot = _get_json(historical_snapshot_url(game_id, final_timecode))
            normalized_rows.extend(normalize_final_game(game, timestamps_payload, final_snapshot))
            ts_rel = Path("raw/games") / f"{game_id}-timestamps.json"
            snap_rel = Path("raw/games") / f"{game_id}-final-{final_timecode}.json"
            ts_sha = write_json(root / ts_rel, timestamps_payload)
            snap_sha = write_json(root / snap_rel, final_snapshot)
            evidence_files.extend([
                {"path": ts_rel.as_posix(), "sha256": ts_sha},
                {"path": snap_rel.as_posix(), "sha256": snap_sha},
            ])
        except Exception as exc:
            failures.append({"game_id": game_id, "reason": f"{type(exc).__name__}:{exc}"})

    rows_rel = Path("normalized/MLB_STATSAPI_HISTORY.jsonl")
    rows_sha = write_jsonl(root / rows_rel, normalized_rows)
    evidence_files.append({"path": rows_rel.as_posix(), "sha256": rows_sha})
    provenance_rel = Path("raw/PROVENANCE.json")
    provenance_sha = write_json(root / provenance_rel, {
        "source_class": "MLB_STATSAPI_HISTORY",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "schedule_url": sched_url,
        "game_source_count": sum(1 for g in games if g["status"] == "Final"),
        "source_policy": {
            "timestamps": "official MLB StatsAPI historical timestamps",
            "final_snapshot": "official MLB StatsAPI feed/live at last timestamp",
            "final_at": "LAST_HISTORICAL_TIMECODE_CONFIRMED_FINAL_UPPER_BOUND",
        },
    })
    evidence_files.append({"path": provenance_rel.as_posix(), "sha256": provenance_sha})
    report = build_shard_report(
        coverage_start=start.isoformat(), coverage_end=end.isoformat(), games=games,
        normalized_rows=normalized_rows, failures=failures, evidence_files=evidence_files,
    )
    report["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    report["schedule_url"] = sched_url
    write_json(root / "shard_report.json", report)
    print(json.dumps({
        "state": report["state"], "coverage_start": report["coverage_start"],
        "coverage_end": report["coverage_end"], "scheduled_final_game_count": report["scheduled_final_game_count"],
        "normalized_final_game_count": report["normalized_final_game_count"], "failures": len(report["failures"]),
        "blockers": report["blockers"],
    }, sort_keys=True))
    return 0 if report["state"] == "SHARD_READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
