"""Unit tests for sportsedge/mlb_sp_rgs.py (538-adapted rGS engine).

No network: gameLog payloads are hand-built. Pins the 538 game-score
formula, the fitted calibration constants, the point-in-time filter, and
the fail-closed gates. The empirical study lives in
scripts/study_sp_ablation.py.
"""
import pytest

from sportsedge import mlb_sp_rgs as rgs
from datetime import date


def _split(day, k=8, bb=1, h=5, r=2, hr=1, ip="7.0", gs_flag=1, opp=999):
    return {"date": day, "season": "2026", "opponent": {"id": opp},
            "stat": {"gamesStarted": gs_flag, "strikeOuts": k,
                     "baseOnBalls": bb, "hits": h, "runs": r,
                     "homeRuns": hr, "inningsPitched": ip}}


def _gamelog(days, **kw):
    return {"stats": [{"group": {"displayName": "pitching"},
                       "splits": [_split(d, **kw) for d in days]}]}


def _days(n, start="2026-08-01", step=6):
    from datetime import date as d, timedelta
    day = d.fromisoformat(start)
    return [(day + timedelta(days=step * i)).isoformat() for i in range(n)]


def test_game_score_matches_538_formula():
    # 47.4 + K + 1.5*outs - 2*BB - 2*H - 3*R - 4*HR
    # 8K, 21 outs, 1BB, 5H, 2R, 1HR -> 47.4+8+31.5-2-10-6-4 = 64.9
    assert rgs.game_score(8, 21, 1, 5, 2, 1) == 64.9


def test_calibration_constants_pinned_to_study():
    # V2 (league-relative, raw): fit 2021-2022, eval 2023-2024 identical
    # sample. Re-run scripts/study_sp_ablation.py before changing these.
    assert rgs.SP_RGS_GAMMA == -0.0699
    assert rgs.SP_RGS_INTERCEPT == 0.014
    assert rgs.LEAGUE_MEAN_GS == 51.54
    assert rgs.SP_RGS_ADJ_CAP == 2.0
    assert rgs.MIN_PITCHER_STARTS == 5


def test_fetch_gamelog_starts_point_in_time_and_flag():
    days = _days(8)
    log = _gamelog(days, k=8, bb=1, h=5, r=2, hr=1, ip="7.0")
    # one relief appearance must be ignored; one future start excluded
    log["stats"][0]["splits"][0]["stat"]["gamesStarted"] = 0
    log["stats"][0]["splits"][-1]["date"] = "2026-10-20"
    starts = rgs.fetch_gamelog_starts(lambda url: log, 1, 2026, date(2026, 10, 12))
    assert len(starts) == 6
    assert all(s["date"] < "2026-10-12" for s in starts)
    assert starts[0]["game_score"] == 64.9


def test_fetch_gamelog_starts_bad_shape_raises():
    with pytest.raises(rgs.Unverifiable):
        rgs.fetch_gamelog_starts(lambda url: {"nope": 1}, 1, 2026, date(2026, 10, 12))
    bad = _gamelog(_days(6))
    bad["stats"][0]["splits"][0]["stat"]["inningsPitched"] = "7.3"
    with pytest.raises(rgs.Unverifiable):
        rgs.fetch_gamelog_starts(lambda url: bad, 1, 2026, date(2026, 10, 12))


def test_pitcher_rgs_min_starts_and_opener_gates():
    log = _gamelog(_days(4))
    with pytest.raises(rgs.Unverifiable):
        rgs.pitcher_rgs(lambda url: log, 1, 2026, date(2026, 10, 12))
    opener = _gamelog(_days(6), ip="2.1")  # 2.33 IP/start
    with pytest.raises(rgs.Unverifiable) as ei:
        rgs.pitcher_rgs(lambda url: opener, 1, 2026, date(2026, 10, 12))
    assert "opener" in str(ei.value).lower()


def test_suppression_math_and_cap():
    # rGS 86.4 (gap 34.86): raw = 0.014 - 0.0699*34.86 = -2.42 -> cap -2.0
    log = _gamelog(_days(20), k=11, bb=1, h=3, r=0, hr=0, ip="8.0")
    adj, audit = rgs.suppression_for_starter(lambda url: log, 1, 2026,
                                             date(2026, 10, 12))
    assert audit["pitcher_rgs"] == 86.4
    assert audit["rgs_gap_vs_league"] == 34.86
    assert adj == -2.0
    # below-average arm boosts the opponent total
    bad = _gamelog(_days(12), k=3, bb=3, h=8, r=5, hr=2, ip="5.0")
    adj2, _ = rgs.suppression_for_starter(lambda url: bad, 1, 2026,
                                          date(2026, 10, 12))
    assert adj2 > 0


def test_trailing_window_uses_last_20():
    log = _gamelog(_days(25, start="2026-06-01", step=3),
                   k=8, bb=1, h=5, r=2, hr=1, ip="7.0")
    # first 5 starts are disasters; they must age out of the 20-start window
    for s in log["stats"][0]["splits"][:5]:
        s["stat"].update({"hits": 12, "runs": 9, "homeRuns": 4})
    r, n, audit = rgs.pitcher_rgs(lambda url: log, 1, 2026, date(2026, 10, 12))
    assert audit["starts_used"] == 20
    assert r == 64.9
