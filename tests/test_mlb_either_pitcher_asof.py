from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import mlb_either_pitcher_asof as ep
from sportsedge.mlb_f5_team_total_ladder import F5LadderError

T0 = datetime(2025, 4, 1, 23, tzinfo=timezone.utc)


def _log(pk, hits, started=True, gt="R"):
    return {"stats": [{"splits": [{"date": "x", "gameType": gt, "game": {"gamePk": pk},
                                   "stat": {"gamesStarted": int(started), "hits": hits, "baseOnBalls": 1,
                                            "earnedRuns": 2}}]}]}


def _logs(base, hits):
    out = []
    for i, h in enumerate(hits):
        out += ep.parse_pitcher_gamelog(_log(base + i, h))
    return out


STARTS = {pk: T0 + timedelta(days=5 * (pk % 100)) for pk in list(range(100, 120)) + list(range(200, 220))}


def test_future_and_not_final_starts_excluded_and_order_invariant():
    logs = _logs(100, [5, 6, 7, 4, 5, 9, 20])
    as_of = STARTS[105] + timedelta(hours=2)  # 105 started but not final; 106 future
    a = ep.pitcher_count_pmf(logs, market="EITHER_PITCHER_HITS_ALLOWED", as_of=as_of, start_by_pk=STARTS)
    assert a["game_pks"] == [100, 101, 102, 103, 104]
    b = ep.pitcher_count_pmf(list(reversed(logs)), market="EITHER_PITCHER_HITS_ALLOWED", as_of=as_of,
                             start_by_pk=STARTS)
    assert a == b


def test_relief_unknown_game_and_postseason_excluded():
    logs = _logs(100, [5, 6, 7, 4, 5])
    logs += ep.parse_pitcher_gamelog(_log(110, 1, started=False))
    logs += ep.parse_pitcher_gamelog(_log(999, 1))  # no schedule start -> fail closed
    logs += ep.parse_pitcher_gamelog(_log(111, 1, gt="P"))
    r = ep.pitcher_count_pmf(logs, market="EITHER_PITCHER_HITS_ALLOWED", as_of=T0 + timedelta(days=400),
                             start_by_pk=STARTS)
    assert r["game_pks"] == [100, 101, 102, 103, 104]
    with pytest.raises(F5LadderError):
        ep.pitcher_count_pmf(logs[:4], market="EITHER_PITCHER_HITS_ALLOWED", as_of=T0 + timedelta(days=400),
                             start_by_pk=STARTS)


def test_ladder_from_real_shaped_logs_is_research_only():
    away, home = _logs(100, [5, 6, 7, 4, 5, 6]), _logs(200, [3, 4, 5, 6, 2, 8])
    prior = [0.0] * 16
    prior[5] = 1.0
    out = ep.price_either_pitcher(away, home, market="EITHER_PITCHER_HITS_ALLOWED", lines=[4.5, 5.5, 6.5],
                                  as_of=T0 + timedelta(days=400), start_by_pk=STARTS, prior_pmf=prior)
    overs = [r["over"] for r in out["ladder"]]
    assert overs == sorted(overs, reverse=True)
    assert out["settlement_status"] == "UNVERIFIED_DK_RULES" and out["play_authority"] is False
    assert out["market_baseline"] == "MISSING" and out["away_starts"] == 6
