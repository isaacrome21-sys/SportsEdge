"""Lane 3: NFL props priced nothing because nflverse renamed/removed columns.

Auto run on #2551 (2026-10-24) recorded:
  player_stats: MISSING:NFLVERSE player-stats schema unsupported:recent_team
  injuries:     MISSING:NFLVERSE injury schema unsupported:date_modified
so 136/136 prop rows were NO_MODEL INJURY_SOURCE_REQUIRED_FOR_LIVE_PROPS.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.injury_report_source import fetch_nflverse_injuries
from sportsedge.sports.nfl.live_role_source import fetch_nflverse_player_stats
from sportsedge.sports.nfl.nflverse_stats_schema_adapter import fetch_player_stats_2025_schema

STATS_2026_HEADER = ("player_id,player_name,player_display_name,position,position_group,headshot_url,"
    "season,week,season_type,game_id,team,opponent_team,completions,attempts,passing_yards,passing_tds,"
    "passing_interceptions,carries,rushing_yards,rushing_tds,receptions,targets,receiving_yards,receiving_tds")
INJ_2026_HEADER = ("season,season_type,game_type,team,week,gsis_id,position,full_name,first_name,last_name,"
    "report_primary_injury,report_secondary_injury,report_status,practice_primary_injury,"
    "practice_secondary_injury,practice_status")


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _opener(text):
    return lambda req, timeout=0: _Resp(text.encode("utf-8"))


def test_2026_player_stats_schema_with_team_and_passing_interceptions_loads():
    csv_text = STATS_2026_HEADER + "\nqb1,A QB,A QB,QB,QB,,2026,6,REG,g,PIT,NO,20,30,250,2,1,3,10,0,0,0,0,0\n"
    # The frozen V1 loader (live_role_source.py, blob-pinned by the forward
    # lock) rejects the renamed columns; the adapter maps exact renames only.
    with pytest.raises(NFLContextError, match="recent_team"):
        fetch_nflverse_player_stats(seasons=[2026], opener=_opener(csv_text))
    rows, receipts = fetch_player_stats_2025_schema(seasons=[2026], opener=_opener(csv_text))
    assert rows[0]["recent_team"] == "PIT"
    assert rows[0]["interceptions"] == "1"
    assert receipts[0]["season"] == "2026"
    assert receipts[0]["upstream_raw_sha256"] != receipts[0]["raw_sha256"]
    assert receipts[0]["schema_renames"] == ["team->recent_team", "passing_interceptions->interceptions"]


def test_player_stats_without_any_team_column_still_fails_closed():
    header = STATS_2026_HEADER.replace(",team,", ",")
    csv_text = header + "\nqb1,A QB,A QB,QB,QB,,2026,6,REG,g,NO,20,30,250,2,1,3,10,0,0,0,0,0\n"
    with pytest.raises(NFLContextError, match="recent_team"):
        fetch_player_stats_2025_schema(seasons=[2026], opener=_opener(csv_text))


def test_adapter_rejects_file_carrying_both_legacy_and_new_team_columns():
    header = STATS_2026_HEADER.replace(",team,", ",team,recent_team,")
    csv_text = header + "\nqb1,A QB,A QB,QB,QB,,2026,6,REG,g,PIT,PIT,NO,20,30,250,2,1,3,10,0,0,0,0,0\n"
    with pytest.raises(NFLContextError) as info:
        fetch_player_stats_2025_schema(seasons=[2026], opener=_opener(csv_text))
    assert "ambiguous" in str(info.value.__cause__)


def test_frozen_v1_surface_is_untouched():
    import subprocess
    lock = json.load(open("config/research/nfl_market_context_prop_v1_2026_forward_lock.json"))
    for item in lock["candidate_identity"]["code_surface"]:
        blob = subprocess.check_output(["git", "hash-object", item["path"]], text=True).strip()
        assert blob == item["git_blob_sha1"], item["path"]


def test_plain_injury_fetch_without_row_timestamps_still_fails_closed():
    csv_text = INJ_2026_HEADER + "\n2026,REG,REG,PIT,7,00-1,WR,X Y,X,Y,Knee,,Out,Knee,,Did Not Participate In Practice\n"
    with pytest.raises(NFLContextError, match="date_modified"):
        fetch_nflverse_injuries(season=2026, opener=_opener(csv_text))


def _snapshot(retrieved):
    from sportsedge.sports.nfl.injury_report_source import fetch_nflverse_injury_snapshot
    csv_text = INJ_2026_HEADER + "\n2026,REG,REG,PIT,7,00-1,WR,X Y,X,Y,Knee,,Out,Knee,,Did Not Participate In Practice\n"
    return fetch_nflverse_injury_snapshot(season=2026, now=lambda: retrieved, opener=_opener(csv_text))


def test_injury_snapshot_stamps_rows_with_retrieval_time_and_is_hash_bound():
    from sportsedge.sports.nfl.injury_report_source import load_injury_snapshot
    got = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
    snap = json.loads(json.dumps(_snapshot(got)))
    assert snap["date_modified_source"] == "RETRIEVAL_TIME_UPPER_BOUND"
    rows, uri, digest = load_injury_snapshot(snap, season=2026, observed_at="2026-10-24T21:06:00+00:00")
    assert rows[0]["date_modified"] == got.isoformat()
    assert digest == snap["raw_sha256"] and uri.endswith("injuries_2026.csv")


@pytest.mark.parametrize("mutate,match", [
    (lambda s: s.update(raw_csv=s["raw_csv"].replace("Out", "Active")), "hash"),
    (lambda s: s.update(season=2025), "season"),
    (lambda s: s.update(schema="X"), "schema"),
    (lambda s: s.update(date_modified_source="NFLVERSE_ROW"), "stamp source"),
])
def test_injury_snapshot_tamper_fails_closed(mutate, match):
    from sportsedge.sports.nfl.injury_report_source import load_injury_snapshot
    snap = _snapshot(datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc))
    mutate(snap)
    with pytest.raises(NFLContextError, match=match):
        load_injury_snapshot(snap, season=2026, observed_at="2026-10-24T21:06:00+00:00")


def test_injury_snapshot_retrieved_after_observation_is_post_pit_and_rejected():
    from sportsedge.sports.nfl.injury_report_source import load_injury_snapshot
    snap = _snapshot(datetime(2026, 10, 24, 21, 10, tzinfo=timezone.utc))
    with pytest.raises(NFLContextError, match="after observation"):
        load_injury_snapshot(snap, season=2026, observed_at="2026-10-24T21:06:00+00:00")



def test_collector_writes_injury_snapshot_before_ticket_observation(tmp_path):
    from scripts.collect_nfl_auto_props import write_injury_snapshot
    board = {"games": [{"commence_time": "2026-10-25T17:00:00Z"}]}
    seen = {}
    def fake(*, season):
        seen["season"] = season
        return {"schema": "S", "season": season}
    out = write_injury_snapshot(board, tmp_path, fetch=fake)
    assert out["status"] == "READY" and seen["season"] == 2026
    assert json.loads((tmp_path / "nfl_injury_snapshot.json").read_text())["season"] == 2026


def test_collector_snapshot_failure_writes_nothing_and_stays_blocked(tmp_path):
    from scripts.collect_nfl_auto_props import write_injury_snapshot
    def boom(*, season):
        raise NFLContextError("NFLVERSE injury fetch failed")
    out = write_injury_snapshot({"games": [{"commence_time": "2026-10-25T17:00:00Z"}]}, tmp_path, fetch=boom)
    assert out["status"] == "BLOCKED" and not (tmp_path / "nfl_injury_snapshot.json").exists()
    mixed = {"games": [{"commence_time": "2026-01-04T17:00:00Z"}, {"commence_time": "2026-10-25T17:00:00Z"}]}
    assert write_injury_snapshot(mixed, tmp_path, fetch=boom)["reason"] == "INJURY_SNAPSHOT_SEASON_AMBIGUOUS"


def test_collector_main_snapshots_before_now_is_taken():
    import inspect
    from scripts import collect_nfl_auto_props as c
    src = inspect.getsource(c.main)
    assert src.index("write_injury_snapshot(") < src.index("now=datetime.now(")
