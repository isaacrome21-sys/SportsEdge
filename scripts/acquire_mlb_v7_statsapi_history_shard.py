#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from sportsedge.mlb_v7_final_timecode import archived_final_feed_rows, latest_confirmed_final_rows
from sportsedge.mlb_v7_statsapi_history import build_shard_report, detailed_status_by_game, write_json, write_jsonl
from sportsedge.mlb_v7_travel_history import BASE, _get_json, extract_timecodes, historical_snapshot_url, schedule_games, schedule_url, snapshot_status, timestamps_url


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
    final_source_counts = {"historical_timecode": 0, "archived_full_feed": 0}
    for game in games:
        if game["status"] != "Final":
            continue
        game_id = int(game["game_id"])
        try:
            timestamps_payload = _get_json(timestamps_url(game_id))
            timecodes = extract_timecodes(timestamps_payload)
            last_timecode = timecodes[-1]
            last_snapshot = _get_json(historical_snapshot_url(game_id, last_timecode))
            if snapshot_status(last_snapshot) == "Final":
                rows, final_timecode, final_snapshot = latest_confirmed_final_rows(
                    game, [last_timecode], lambda _: last_snapshot,
                )
                source_kind = "historical_timecode"
                snap_rel = Path("raw/games") / f"{game_id}-final-{final_timecode}.json"
            else:
                archived_feed = _get_json(f"{BASE}/api/v1.1/game/{game_id}/feed/live")
                try:
                    rows, final_timecode = archived_final_feed_rows(game, archived_feed)
                    final_snapshot = archived_feed
                    source_kind = "archived_full_feed"
                    snap_rel = Path("raw/games") / f"{game_id}-archived-final-feed.json"
                except Exception:
                    rows, final_timecode, final_snapshot = latest_confirmed_final_rows(
                        game,
                        timecodes,
                        lambda timecode: _get_json(historical_snapshot_url(game_id, timecode)),
                    )
                    source_kind = "historical_timecode"
                    snap_rel = Path("raw/games") / f"{game_id}-final-{final_timecode}.json"
            normalized_rows.extend(rows)
            final_source_counts[source_kind] += 1
            ts_rel = Path("raw/games") / f"{game_id}-timestamps.json"
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
        "final_source_counts": final_source_counts,
        "source_policy": {
            "timestamps": "official MLB StatsAPI historical timestamps",
            "primary_final_at": "latest historical timecode when its historical snapshot explicitly confirms Final",
            "fallback_final_at": "archived full v1.1 feed metaData.timeStamp only when status=Final, gameEvents includes game_finished, and logicalEvents includes gameStateChangeToGameOver",
            "fallback_is_not_retrieval_time": True,
        },
    })
    evidence_files.append({"path": provenance_rel.as_posix(), "sha256": provenance_sha})
    report = build_shard_report(
        coverage_start=start.isoformat(), coverage_end=end.isoformat(), games=games,
        normalized_rows=normalized_rows, failures=failures, evidence_files=evidence_files,
    )
    report["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    report["schedule_url"] = sched_url
    report["final_source_counts"] = final_source_counts
    write_json(root / "shard_report.json", report)
    print(json.dumps({
        "state": report["state"], "coverage_start": report["coverage_start"],
        "coverage_end": report["coverage_end"], "scheduled_final_game_count": report["scheduled_final_game_count"],
        "normalized_final_game_count": report["normalized_final_game_count"], "failures": len(report["failures"]),
        "failure_details": report["failures"], "final_source_counts": final_source_counts,
        "blockers": report["blockers"],
    }, sort_keys=True))
    return 0 if report["state"] == "SHARD_READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
