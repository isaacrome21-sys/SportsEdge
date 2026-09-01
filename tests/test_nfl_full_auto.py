import pytest

import sportsedge.sports.nfl.full_auto as full_auto
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


def test_full_auto_passes_depth_rows_and_provenance(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        full_auto,
        "fetch_nflverse_depth_charts",
        lambda **kwargs: ([{"dt": "2026-09-01", "team": "CHI"}], "https://example.test/depth.csv", "a" * 64),
    )

    def fake_slate(**kwargs):
        captured.update(kwargs)
        return {
            "as_of_utc": "2026-09-01T13:00:00+00:00",
            "collection_mode": "AUTO",
            "game_count": 0,
            "games": [],
            "depth_chart_source_sha256": kwargs.get("depth_chart_source_sha256"),
            "model_p_eligible": False,
            "truth_gate_eligible": False,
        }

    monkeypatch.setattr(full_auto, "build_nfl_auto_context_slate", fake_slate)
    payload = full_auto.build_nfl_full_auto_slate(as_of="2026-09-01T13:00:00+00:00", season=2026)
    assert captured["depth_chart_rows"][0]["team"] == "CHI"
    assert captured["depth_chart_source_uri"] == "https://example.test/depth.csv"
    assert captured["depth_chart_source_sha256"] == "a" * 64
    assert payload["automation"]["depth_chart_status"] == "AVAILABLE"
    assert payload["automation"]["operator_game_list_required"] is False


def test_full_auto_depth_failure_is_scoped_and_does_not_infer(monkeypatch):
    def broken(**kwargs):
        raise NFLContextError("provider unavailable")

    captured = {}
    monkeypatch.setattr(full_auto, "fetch_nflverse_depth_charts", broken)

    def fake_slate(**kwargs):
        captured.update(kwargs)
        return {
            "as_of_utc": "2026-09-01T13:00:00+00:00",
            "collection_mode": "AUTO",
            "game_count": 0,
            "games": [],
            "depth_chart_source_sha256": None,
            "model_p_eligible": False,
            "truth_gate_eligible": False,
        }

    monkeypatch.setattr(full_auto, "build_nfl_auto_context_slate", fake_slate)
    payload = full_auto.build_nfl_full_auto_slate(as_of="2026-09-01T13:00:00+00:00", season=2026)
    assert captured["depth_chart_rows"] is None
    assert captured["depth_chart_source_uri"] is None
    assert captured["depth_chart_source_sha256"] is None
    assert payload["automation"]["depth_chart_status"].startswith("MISSING:")
