from __future__ import annotations
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from sportsedge.mlb_v7_statsapi_history import build_shard_report, finalize_history, month_windows, write_json, write_jsonl
from sportsedge.mlb_v7_travel_history import HistoricalGameRow


def row(game_id: int, team_id: int, opp: int, day: str = "2023-01-10"):
    return HistoricalGameRow(
        game_id=game_id, team_id=team_id, opponent_team_id=opp, venue_id=15,
        game_start_time=f"{day}T18:00:00+00:00", status="Final",
        final_at=f"{day}T21:00:00+00:00",
        final_at_semantics="LAST_HISTORICAL_TIMECODE_CONFIRMED_FINAL_UPPER_BOUND",
        official_date=day, game_type="R", side="away" if team_id < opp else "home",
        final_timecode=day.replace("-", "") + "_210000",
    )


def game(game_id=1, day="2023-01-10", status="Final", detailed_status="Final"):
    return {
        "game_id": game_id, "away_team_id": 10, "home_team_id": 20, "venue_id": 15,
        "game_start_time": f"{day}T18:00:00+00:00", "status": status,
        "official_date": day, "game_type": "R", "detailed_status": detailed_status,
    }


def make_shard(root: Path, label: str, start: str, end: str, game_id: int):
    shard = root / label
    rows = [asdict(row(game_id, 10, 20, start)), asdict(row(game_id, 20, 10, start))]
    rows_rel = Path("normalized/MLB_STATSAPI_HISTORY.jsonl")
    rows_sha = write_jsonl(shard / rows_rel, rows)
    schedule_rel = Path("raw/schedule.json")
    schedule_sha = write_json(shard / schedule_rel, {"games": [game_id]})
    report = {
        "state": "SHARD_READY", "coverage_start": start, "coverage_end": end,
        "evidence_files": [
            {"path": rows_rel.as_posix(), "sha256": rows_sha},
            {"path": schedule_rel.as_posix(), "sha256": schedule_sha},
        ],
    }
    write_json(shard / "shard_report.json", report)


def test_month_windows_exact():
    assert month_windows(date(2023,1,10), date(2023,3,2)) == [
        (date(2023,1,10), date(2023,1,31)),
        (date(2023,2,1), date(2023,2,28)),
        (date(2023,3,1), date(2023,3,2)),
    ]


def test_shard_ready_requires_two_rows_per_final():
    rows=[row(1,10,20), row(1,20,10)]
    r=build_shard_report(coverage_start="2023-01-01",coverage_end="2023-01-31",
        games=[game()],normalized_rows=rows,failures=[],evidence_files=[{"path":"x","sha256":"0"*64}])
    assert r["state"]=="SHARD_READY"
    assert r["attestation_authority"] is False


def test_shard_blocks_missing_final():
    r=build_shard_report(coverage_start="2023-01-01",coverage_end="2023-01-31",
        games=[game()],normalized_rows=[],failures=[],evidence_files=[])
    assert r["state"]=="SHARD_BLOCKED"
    assert "FINAL_GAMES_MISSING" in r["blockers"]


def test_terminal_nonplayed_is_explicitly_accounted_without_becoming_row():
    r=build_shard_report(coverage_start="2023-01-01",coverage_end="2023-01-31",
        games=[game(status="Preview", detailed_status="Postponed")],normalized_rows=[],failures=[],evidence_files=[])
    assert r["state"]=="SHARD_READY"
    assert r["schedule_dispositions"][0]["disposition"]=="EXCLUDED_TERMINAL_NONPLAYED"


def test_unresolved_nonfinal_blocks():
    r=build_shard_report(coverage_start="2023-01-01",coverage_end="2023-01-31",
        games=[game(status="Preview", detailed_status="Scheduled")],normalized_rows=[],failures=[],evidence_files=[])
    assert r["state"]=="SHARD_BLOCKED"
    assert "HISTORICAL_SCHEDULE_NONFINAL_UNRESOLVED" in r["blockers"]


def test_finalize_refuses_missing_month(tmp_path: Path):
    out=tmp_path/"out"
    r=finalize_history(shard_root=tmp_path/"shards",coverage_start="2023-01-01",
        coverage_end="2023-02-28",output_root=out)
    assert r["state"]=="BLOCKED_INCOMPLETE_HISTORY"
    assert r["attestation_written"] is False
    assert len(r["blockers"])==2


def test_finalize_hash_tamper_blocks(tmp_path: Path):
    shards=tmp_path/"shards"
    make_shard(shards,"2023-01","2023-01-01","2023-01-31",1)
    (shards/"2023-01"/"normalized/MLB_STATSAPI_HISTORY.jsonl").write_text("tampered\n")
    r=finalize_history(shard_root=shards,coverage_start="2023-01-01",
        coverage_end="2023-01-31",output_root=tmp_path/"out")
    assert r["state"]=="BLOCKED_INCOMPLETE_HISTORY"
    assert any("SHA_MISMATCH" in x for x in r["blockers"])


def test_finalize_complete_writes_only_full_attestation(tmp_path: Path):
    shards=tmp_path/"shards"
    make_shard(shards,"2023-01","2023-01-01","2023-01-31",1)
    make_shard(shards,"2023-02","2023-02-01","2023-02-28",2)
    out=tmp_path/"out"
    r=finalize_history(shard_root=shards,coverage_start="2023-01-01",
        coverage_end="2023-02-28",output_root=out)
    assert r["state"]=="READY_TO_ATTEST"
    assert r["attestation_written"] is True
    att=json.loads((out/"attestations/MLB_STATSAPI_HISTORY.json").read_text())
    assert att["semantics"]["complete_schedule_chain"] is True
    assert att["coverage_start"]=="2023-01-01"
    assert len(att["evidence_files"])==2


def test_finalize_overlap_blocks(tmp_path: Path):
    shards=tmp_path/"shards"
    make_shard(shards,"2023-01","2023-01-01","2023-01-31",1)
    make_shard(shards,"2023-02","2023-02-01","2023-02-28",1)
    r=finalize_history(shard_root=shards,coverage_start="2023-01-01",
        coverage_end="2023-02-28",output_root=tmp_path/"out")
    assert r["state"]=="BLOCKED_INCOMPLETE_HISTORY"
    assert any("SHARD_GAME_OVERLAP" in x for x in r["blockers"])
