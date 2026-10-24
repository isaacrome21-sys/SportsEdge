"""Lane 1 audit follow-ups (#2384): the decompressed NFL side model must not
reach any candidate list or emit unbacktested derivative prices."""
from datetime import datetime, timezone

from sportsedge import phone_display
from sportsedge.live_run_it import run_live_full
from sportsedge.team_half_pricing import _estimate
from tests.test_live_run_it import NFL_NOW, _clean_injuries, nfl_canned_getter, nfl_line

import pytest


def test_nfl_live_sides_never_reach_live_candidates_even_with_huge_ev():
    lines = [nfl_line(odds=900), nfl_line(side="AWAY", odds=900),
             nfl_line(market="SPREAD", side="HOME", line=20.5, odds=900),
             nfl_line(market="SPREAD", side="AWAY", line=20.5, odds=900)]
    card = run_live_full({"lines": lines}, now=NFL_NOW, min_ev=0.0,
                         getter=nfl_canned_getter(_clean_injuries()))
    assert card["live_candidates"] == []
    priced = [r for r in card["evaluated_rows"] if r.get("ev_per_dollar") is not None]
    assert priced, card["evaluated_rows"]
    assert any(r["ev_per_dollar"] > 0 for r in priced)
    for r in priced:
        assert r["status"] == "LIVE_WATCH_NFL_SIDE_UNVALIDATED"
        assert "ISSUE_2384" in r["reason"]


def test_phone_display_labels_new_nfl_side_model():
    row = {"context_notes": ["NFL_SIDE_MARGIN_KEYNUM_V1_DECOMPRESSED"]}
    assert phone_display._model_version(row, "NFL") == "NFL_SIDE_MARGIN_KEYNUM_V1"
    assert phone_display._model_version({"context_notes": []}, "NFL") == "NFL_SIDES_PRIOR_COMPRESSED_2384"


def test_nfl_team_half_derivatives_keep_pre_lane1_ratings(monkeypatch):
    # Team totals / 1H are not backtested with the decompressed side rating:
    # they must price from the pre-Lane-1 per-team ratings, unchanged.
    from sportsedge import team_half_pricing as thp
    from artifacts import free_models as fm
    ctx = {"home_rating": 5.0, "away_rating": -5.0,
           "home_rating_pre_nfl_side_v1": 1.2, "away_rating_pre_nfl_side_v1": -1.2,
           "home_injury_pts": 0.0, "away_injury_pts": 0.0, "weather_total_adj": 0.0}
    kick = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)
    notes = ["HOME_HISTORY_COUNT:5", "AWAY_HISTORY_COUNT:5",
             "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL", "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL",
             "WEATHER:INDOOR_VERIFIED"]

    class P:
        def fixture(self, *a):
            return (None, {"id": "1"})
    monkeypatch.setattr(fm, "context_for", lambda *a, **k: (ctx, kick, notes))
    hm, am, *_ = thp._scoring("NFL", "H", "A", kick.isoformat(), datetime(2026, 10, 11, tzinfo=timezone.utc), P())
    base, _, _, hfa = fm.PRIORS["NFL"]
    assert hm == pytest.approx(base + hfa / 2 + 1.2)
    assert am == pytest.approx(base - hfa / 2 - 1.2)

