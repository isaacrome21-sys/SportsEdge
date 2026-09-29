from __future__ import annotations

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.nflverse_prop_ingest import build_nflverse_prop_opportunity_provider


def _kwargs():
    return dict(
        game_id="2026_03_PHI_CHI",
        kickoff="2026-09-29T00:15:00Z",
        observed_at="2026-09-28T23:00:00Z",
        source_uri="https://github.com/nflverse/nflverse-data/releases",
        snap_rows=[
            {"season":2026,"week":1,"player_id":"qb1","team":"CHI","position":"QB","offense_pct":1.0,"games":2},
            {"season":2026,"week":2,"player_id":"rb1","team":"CHI","position":"RB","offense_pct":0.65,"games":2},
        ],
        player_rows=[
            {"season":2026,"week":1,"player_id":"qb1","team":"CHI","position":"QB","attempts":60,"carries":4,"targets":0},
            {"season":2026,"week":2,"player_id":"rb1","team":"CHI","position":"RB","attempts":0,"carries":30,"targets":8},
        ],
        pbp_rows=[],
    )


def test_builds_market_blind_pit_provider():
    out = build_nflverse_prop_opportunity_provider(**_kwargs())
    assert out["status"] == "AVAILABLE"
    players = {p["player_id"]: p for p in out["payload"]["players"]}
    assert players["rb1"]["carry_share"] == pytest.approx(30 / 34)
    assert players["rb1"]["route_participation"] is None
    assert len(out["source_sha256"]) == 64


def test_rejects_post_kickoff_snapshot():
    kw = _kwargs()
    kw["observed_at"] = kw["kickoff"]
    with pytest.raises(NFLContextError, match="before kickoff"):
        build_nflverse_prop_opportunity_provider(**kw)


def test_rejects_market_contamination():
    kw = _kwargs()
    kw["player_rows"][0]["odds"] = -110
    with pytest.raises(NFLContextError, match="market input forbidden"):
        build_nflverse_prop_opportunity_provider(**kw)


def test_rejects_target_week_row_from_rolling_source():
    kw = _kwargs()
    kw["player_rows"][0]["week"] = 3
    with pytest.raises(NFLContextError, match="not pre-target PIT data"):
        build_nflverse_prop_opportunity_provider(**kw)


def test_rejects_row_without_pit_markers():
    kw = _kwargs()
    del kw["snap_rows"][0]["week"]
    with pytest.raises(NFLContextError, match="missing season/week PIT markers"):
        build_nflverse_prop_opportunity_provider(**kw)
