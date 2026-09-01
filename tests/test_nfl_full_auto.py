import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.full_auto import fetch_nflverse_depth_charts


class Response:
    def __init__(self, raw: bytes):
        self.raw = raw
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.raw


def test_fetch_nflverse_depth_charts_2025_plus_schema():
    raw = b"dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,pos_name,pos_abb,pos_slot,pos_rank\n2026-09-01,CHI,Player,1,2,3,OL,4,Tackle,LT,1,1\n"
    def opener(req, timeout=20):
        assert req.full_url.endswith("depth_charts_2026.csv")
        return Response(raw)
    rows, uri, digest = fetch_nflverse_depth_charts(season=2026, opener=opener)
    assert rows[0]["team"] == "CHI"
    assert uri.endswith("depth_charts_2026.csv")
    assert len(digest) == 64


def test_depth_chart_schema_fails_closed():
    raw = b"foo,bar\n1,2\n"
    with pytest.raises(NFLContextError, match="schema unsupported"):
        fetch_nflverse_depth_charts(season=2026, opener=lambda req, timeout=20: Response(raw))
