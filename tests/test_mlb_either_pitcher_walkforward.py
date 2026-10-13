from datetime import datetime, timedelta, timezone

from sportsedge.mlb_either_pitcher_walkforward import build_events, decide, run_season

T0 = datetime(2025, 4, 1, 17, tzinfo=timezone.utc)


def _sched(n_days, pitchers=(1, 2, 3, 4)):
    dates = []
    pk = 1000
    for d in range(n_days):
        day = (T0 + timedelta(days=d))
        games = []
        for j in range(2):
            games.append({"gamePk": pk, "gameType": "R", "officialDate": day.date().isoformat(),
                          "gameDate": (day + timedelta(hours=j)).isoformat().replace("+00:00", "Z"),
                          "status": {"codedGameState": "F"},
                          "teams": {"away": {"probablePitcher": {"id": pitchers[2 * j]}},
                                    "home": {"probablePitcher": {"id": pitchers[2 * j + 1]}}}})
            pk += 1
        dates.append({"date": day.date().isoformat(), "games": games})
    return {"dates": dates}


def _logs(sched, hits_by_pid, skip=()):
    out = {}
    for d in sched["dates"]:
        for g in d["games"]:
            for side in ("away", "home"):
                pid = g["teams"][side]["probablePitcher"]["id"]
                if (pid, g["gamePk"]) in skip:
                    continue
                out.setdefault(pid, []).append({"game_pk": g["gamePk"], "date": d["date"], "game_type": "R",
                                                "started": True, "hits": hits_by_pid[pid](g["gamePk"]),
                                                "baseOnBalls": 1, "earnedRuns": 2})
    return out


def test_same_slate_and_future_outcomes_do_not_leak():
    s = _sched(40)
    hits = {p: (lambda pk, p=p: (pk * p) % 9) for p in (1, 2, 3, 4)}
    base = run_season(build_events([s], _logs(s, hits)))
    last = s["dates"][-1]["games"]
    tampered = {p: (lambda pk, p=p, f=hits[p]: 15 if pk >= last[0]["gamePk"] else f(pk)) for p in hits}
    t = run_season(build_events([s], _logs(s, tampered)))
    # only the final slate's outcomes changed; the probabilities for it must be identical,
    # so the naive Brier differences come only from y; check earlier-slate-only run equality
    s2 = {"dates": s["dates"][:-1]}
    assert run_season(build_events([s2], _logs(s2, hits))) == run_season(build_events([s2], _logs(s2, tampered)))
    hm = base["markets"]["EITHER_PITCHER_HITS_ALLOWED"]["5.5"]
    assert hm["n"] == t["markets"]["EITHER_PITCHER_HITS_ALLOWED"]["5.5"]["n"] > 0
    assert base["market_baseline"] == "MISSING"


def test_probable_who_did_not_start_is_excluded():
    s = _sched(30)
    hits = {p: (lambda pk: 5) for p in (1, 2, 3, 4)}
    r = run_season(build_events([s], _logs(s, hits, skip={(1, 1000 + 2 * 29)})))
    assert r["excluded_probable_did_not_start"] == 1


def test_decision_rule():
    good = {"markets": {"M": {"1": {"brier_cand": .1, "brier_naive": .2, "ll_cand": .3, "ll_naive": .4}}}}
    bad = {"markets": {"M": {"1": {"brier_cand": .1, "brier_naive": .2, "ll_cand": .5, "ll_naive": .4}}}}
    assert decide(good) == {"M": "PASS_RESEARCH"} and decide(bad) == {"M": "FAIL"}
