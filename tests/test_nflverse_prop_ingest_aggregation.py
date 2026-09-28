from __future__ import annotations

import pytest

from sportsedge.sports.nfl.nflverse_prop_ingest import build_nflverse_prop_opportunity_provider


def test_multiple_snap_games_are_aggregated_not_last_row_wins():
    out = build_nflverse_prop_opportunity_provider(
        game_id="2026_03_PHI_CHI",
        kickoff="2026-09-29T00:15:00Z",
        observed_at="2026-09-24T12:00:00Z",
        source_uri="https://github.com/nflverse/nflverse-data-archives/releases",
        snap_rows=[
            {"player_id":"rb1","team":"CHI","position":"RB","offense_pct":60,"offense_snaps":36},
            {"player_id":"rb1","team":"CHI","position":"RB","offense_pct":80,"offense_snaps":48},
        ],
        player_rows=[
            {"player_id":"rb1","team":"CHI","position":"RB","carries":30,"targets":8},
        ],
    )
    p = out["payload"]["players"][0]
    assert p["sample_games"] == 2
    assert p["snap_share"] == pytest.approx(0.70)
