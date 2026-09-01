import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.snap_workload_source import (
    build_prior_snap_workload_inputs,
    fetch_nflverse_snap_counts,
)


class Response:
    def __init__(self, raw: bytes):
        self.raw = raw
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.raw


HEADER = (
    "game_id,pfr_game_id,season,game_type,week,player,pfr_player_id,position,team,opponent,"
    "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n"
)


def test_fetch_snap_counts_validates_schema_and_hashes_exact_bytes():
    raw = (HEADER + "2026_01_GB_CHI,x,2026,REG,1,Player,p1,WR,CHI,GB,50,0.80,0,0,0,0\n").encode()
    rows, uri, digest = fetch_nflverse_snap_counts(
        season=2026,
        opener=lambda req, timeout=20: Response(raw),
    )
    assert rows[0]["team"] == "CHI"
    assert uri.endswith("snap_counts_2026.csv")
    assert len(digest) == 64


def test_snap_counts_schema_drift_fails_closed():
    raw = b"game_id,season,week,team\nx,2026,1,CHI\n"
    with pytest.raises(NFLContextError, match="SCHEMA_UNSUPPORTED"):
        fetch_nflverse_snap_counts(
            season=2026,
            opener=lambda req, timeout=20: Response(raw),
        )


def test_workload_uses_strictly_prior_weeks_and_normalizes_percent():
    rows = [
        {"game_id": "g1", "season": "2026", "game_type": "REG", "week": "1",
         "player": "Player", "pfr_player_id": "p1", "position": "WR", "team": "CHI",
         "opponent": "GB", "offense_snaps": "40", "offense_pct": "75",
         "defense_snaps": "0", "defense_pct": "0", "st_snaps": "0", "st_pct": "0"},
        {"game_id": "g2", "season": "2026", "game_type": "REG", "week": "2",
         "player": "Player", "pfr_player_id": "p1", "position": "WR", "team": "CHI",
         "opponent": "DET", "offense_snaps": "50", "offense_pct": "0.8",
         "defense_snaps": "0", "defense_pct": "0", "st_snaps": "0", "st_pct": "0"},
        {"game_id": "g3", "season": "2026", "game_type": "REG", "week": "3",
         "player": "Player", "pfr_player_id": "p1", "position": "WR", "team": "CHI",
         "opponent": "MIN", "offense_snaps": "60", "offense_pct": "0.9",
         "defense_snaps": "0", "defense_pct": "0", "st_snaps": "0", "st_pct": "0"},
    ]
    out = build_prior_snap_workload_inputs(
        rows=rows,
        season=2026,
        target_week=3,
        team_ids=("CHI", "GB"),
        source_uri="https://example.test/snap.csv",
        source_sha256="a" * 64,
    )
    assert len(out) == 1
    payload = out[0]["source_payload"]
    assert payload["sample_weeks"] == [1, 2]
    assert payload["snaps"] == [40.0, 50.0]
    assert payload["snap_share"] == [0.75, 0.8]
    assert payload["strictly_prior_week_only"] is True
    assert out[0]["player_id"] == "PFR:p1"


def test_same_week_is_excluded_even_if_it_may_have_already_played():
    rows = [{"game_id": "thu", "season": "2026", "game_type": "REG", "week": "4",
             "player": "Player", "pfr_player_id": "p1", "position": "RB", "team": "CHI",
             "opponent": "GB", "offense_snaps": "30", "offense_pct": "0.5",
             "defense_snaps": "0", "defense_pct": "0", "st_snaps": "0", "st_pct": "0"}]
    assert build_prior_snap_workload_inputs(
        rows=rows,
        season=2026,
        target_week=4,
        team_ids=("CHI",),
        source_uri="https://example.test/snap.csv",
        source_sha256="b" * 64,
    ) == []
