"""Synthetic unit checks for NBA scoring-level PIT construction."""
from datetime import datetime, timedelta, timezone
from sportsedge.research.nba_scoring_level_v2 import predict_total


def games(points=115, *, future=False):
    out = []
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for i in range(40):
        dt = base + timedelta(days=i)
        out.append({"game_id": "g" + str(i), "tipoff": dt.isoformat(),
                    "observed_at": (dt + timedelta(hours=4)).isoformat(),
                    "source_ref": "verified-result-archive", 
                    "home": "A" if i % 2 else "B",
                    "away": "B" if i % 2 else "A",
                    "home_pts": points, "away_pts": points})
    if future:
        dt = datetime(2026, 10, 22, tzinfo=timezone.utc)
        out.append({"game_id": "post", "tipoff": dt.isoformat(),
                    "observed_at": (dt + timedelta(hours=4)).isoformat(),
                    "source_ref": "verified-result-archive",
                    "home": "A", "away": "B",
                    "home_pts": 500, "away_pts": 500})
    return out


def test_league_scoring_level_is_learned_not_fixed_226():
    t = "2026-10-21T18:00:00Z"
    high = predict_total(games(126), home="A", away="B", as_of=t)
    low = predict_total(games(107), home="A", away="B", as_of=t)
    assert high["status"] == low["status"] == "RESEARCH_PROJECTION"
    assert abs(high["predicted_total"] - 252) < 1e-9
    assert abs(low["predicted_total"] - 214) < 1e-9
    assert high["market_test"] == "NOT_RUN"


def test_post_asof_result_cannot_change_projection():
    t = "2026-10-21T18:00:00Z"
    base = predict_total(games(), home="A", away="B", as_of=t)
    leaked = predict_total(games(future=True), home="A", away="B", as_of=t)
    assert leaked["future_excluded"] == 1
    assert base["predicted_total"] == leaked["predicted_total"]


def test_same_day_result_after_asof_is_not_prior():
    t = "2026-10-21T18:00:00Z"
    rows = games()
    rows.append({"game_id": "same", "tipoff": "2026-10-21T15:00:00Z",
                 "observed_at": "2026-10-21T19:00:00Z",
                 "source_ref": "verified", "home": "A", "away": "B",
                 "home_pts": 300, "away_pts": 300})
    result = predict_total(rows, home="A", away="B", as_of=t)
    assert result["future_excluded"] == 1
    assert result["predicted_total"] == 230


def test_unverified_result_availability_fails_closed():
    rows = games()
    rows[0].pop("observed_at")
    try:
        predict_total(rows, home="A", away="B", as_of="2026-10-21T18:00:00Z")
    except ValueError as e:
        assert "RESULT_AVAILABLE_INVALID" in str(e)
    else:
        assert False, "unattested availability must refuse"


def test_insufficient_team_history_refuses_without_market_price():
    rows = games()
    rows[0]["home"] = "C"
    result = predict_total(rows, home="C", away="A",
                           as_of="2026-10-21T18:00:00Z")
    assert result["status"] == "REFUSED"
    assert result["reason"] == "NBA_TOTALS_INSUFFICIENT_TEAM_HISTORY"
