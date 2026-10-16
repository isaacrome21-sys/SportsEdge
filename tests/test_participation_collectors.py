"""Collector parsing on recorded sample payloads (real nflverse subsets).

No network: fixtures under tests/fixtures/participation are trimmed copies
of actual nflverse files (2023), plus one deliberately corrupted injury row
(gsis_id blanked) to prove fail-closed identity rejection.
"""

from datetime import datetime, timezone
from pathlib import Path

from sportsedge.participation.archive import ParticipationArchive, sha256_bytes
from sportsedge.participation.collectors import (
    build_pfr_gsis_bridge,
    collect_depth_charts,
    collect_injuries,
    collect_rosters,
    collect_snap_counts,
    load_schedule,
)
from sportsedge.participation.schema import (
    REJ_MISSING_GSIS_ID,
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_ROSTER_STATUS,
    SIGNAL_SNAP_ACTUAL,
    SIGNAL_STARTER_ACTUAL,
)

FIX = Path(__file__).parent / "fixtures" / "participation"
FETCHED = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)


def _raw(name):
    return (FIX / name).read_bytes()


def _schedule():
    return load_schedule(_raw("games_sample.csv"))


def test_injuries_parsing_and_identity_rejection(tmp_path):
    arc = ParticipationArchive(tmp_path)
    receipt = collect_injuries(arc, _schedule(), 2023, _raw("injuries_sample.csv"),
                               "fixture://injuries", FETCHED)
    assert receipt["rows_in"] == 41
    # the crafted row (gsis blanked) is rejected, counted, never repaired
    assert receipt["rejections"].get(REJ_MISSING_GSIS_ID) == 1
    records = arc.load_records(SIGNAL_INJURY_DESIGNATION)
    assert records, "expected designation records"
    for rec in records:
        assert rec.availability_class == "AVAILABLE_HISTORICALLY"
        assert rec.availability_basis.startswith("FINAL_REPORT_RULE")
        # conservative bound precedes the bound game's kickoff
        assert rec.available_from_utc < rec.kickoff_utc
        assert rec.raw_payload_sha256 == sha256_bytes(_raw("injuries_sample.csv"))
    assert arc.load_receipts()[0]["collector"] == "injuries"


def test_rosters_parsing_prior_week_bounds(tmp_path):
    arc = ParticipationArchive(tmp_path)
    receipt = collect_rosters(arc, _schedule(), 2023, _raw("roster_weekly_sample.csv"),
                              "fixture://rosters", FETCHED)
    assert receipt["records_written"] > 100
    records = arc.load_records(SIGNAL_ROSTER_STATUS)
    assert all(r.availability_basis.startswith("PRIOR_WEEK") for r in records)
    assert all(r.payload.get("status") for r in records)


def test_depth_charts_qb_scope(tmp_path):
    arc = ParticipationArchive(tmp_path)
    receipt = collect_depth_charts(arc, _schedule(), 2023,
                                   _raw("depth_charts_sample.csv"),
                                   "fixture://depth", FETCHED)
    assert receipt["notes"]["rows_out_of_scope_non_qb"] > 0
    records = arc.load_records("DEPTH_CHART")
    assert records and all(r.position == "QB" for r in records)
    assert all(r.payload["depth_rank"] in (1, 2, 3) for r in records)


def test_snap_counts_and_starter_derivation(tmp_path):
    arc = ParticipationArchive(tmp_path)
    bridge = build_pfr_gsis_bridge(_raw("roster_weekly_sample.csv"), 2023)
    sched = _schedule()
    receipt = collect_snap_counts(arc, sched, 2023, _raw("snap_counts_sample.csv"),
                                  "fixture://snaps", FETCHED, pfr_to_gsis=bridge)
    snaps = arc.load_records(SIGNAL_SNAP_ACTUAL)
    assert snaps
    assert all(r.availability_class == "AVAILABLE_ONLY_RETROSPECTIVELY" for r in snaps)
    assert all("PREGAME_FEATURE" not in r.permitted_uses for r in snaps)
    starters = arc.load_records(SIGNAL_STARTER_ACTUAL)
    assert starters, "expected derived starter records"
    # Cross-check: derived starter for the WAS-ARI opener matches the
    # schedule's listed QB name for that team.
    game = sched.by_id["2023_01_ARI_WAS"]
    for rec in starters:
        if rec.game_id == "2023_01_ARI_WAS":
            listed = (game["home_qb_name"] if rec.team == game["home_team"]
                      else game["away_qb_name"])
            assert rec.player_name == listed


def test_empty_snap_file_fails_closed(tmp_path):
    arc = ParticipationArchive(tmp_path)
    header_only = (b"game_id,pfr_game_id,season,game_type,week,player,"
                   b"pfr_player_id,position,team,opponent,offense_snaps,"
                   b"offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n")
    receipt = collect_snap_counts(arc, _schedule(), 2012, header_only,
                                  "fixture://empty", FETCHED)
    assert receipt["records_written"] == 0
    assert receipt["rejections"].get("SOURCE_FILE_EMPTY") == 1
