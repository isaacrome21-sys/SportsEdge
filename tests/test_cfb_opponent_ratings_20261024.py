"""t273: opponent-adjusted CFB offense/defense ratings (SCREEN, NOT_VALIDATED)."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cfb import opponent_ratings as orr
from artifacts.free_models import CONTEXT_KEYS, PRIORS, model_probability, score_means

T0 = datetime(2025, 9, 1, tzinfo=timezone.utc)


def g(day, home, away, hs, as_, neutral=False):
    return {"date": (T0 + timedelta(days=day)).isoformat(), "home": home, "away": away,
            "hs": float(hs), "as": float(as_), "neutral": neutral}


def _league():
    # S1,S2 strong; W1,W2 weak. A only beats weak teams big; B plays strong teams close.
    games = []
    d = 0
    for _ in range(4):
        games += [g(d, "S1", "W1", 45, 10), g(d, "S2", "W2", 42, 14), g(d + 1, "S1", "S2", 28, 27)]
        d += 7
    games += [g(d, "A", "W1", 41, 14), g(d, "A", "W2", 38, 10),
              g(d + 1, "B", "S1", 24, 31), g(d + 1, "B", "S2", 27, 31)]
    return games


def test_opponent_adjustment_ranks_schedule_strength():
    r = orr.fit_ratings(_league(), as_of=T0 + timedelta(days=60), lam=1.0)
    net = {t: r["teams"][t]["off"] + r["teams"][t]["def"] for t in r["teams"]}
    # raw average margin: A +27.5, B -5.5; opponent-adjusted they must be far closer
    assert (net["A"] - net["B"]) < 0.5 * 33


def test_no_lookahead_strictly_before_kickoff():
    games = _league()
    cut = T0 + timedelta(days=20)
    a = orr.fit_ratings(games, as_of=cut, lam=2.0)
    changed = [dict(x, hs=x["hs"] + 50) if x["date"] >= cut.isoformat() else x for x in games]
    b = orr.fit_ratings(changed, as_of=cut, lam=2.0)
    assert a == b
    # a game AT the as_of instant is excluded too
    at = [g(20, "S1", "W1", 99, 0)]
    c = orr.fit_ratings(games + at, as_of=cut, lam=2.0)
    assert c == a


def test_offense_defense_separate_drive_totals():
    games = []
    for d in range(0, 40, 7):
        games += [g(d, "O1", "X", 50, 45), g(d, "O2", "Y", 48, 44),
                  g(d + 1, "D1", "X", 14, 10), g(d + 1, "D2", "Y", 13, 9)]
    r = orr.fit_ratings(games, as_of=T0 + timedelta(days=60), lam=1.0)
    hi = sum(orr.predict(r, "O1", "O2"))
    lo = sum(orr.predict(r, "D1", "D2"))
    assert hi - lo > 30


def test_prior_used_when_no_games_and_shrunk_by_rho():
    prior = {"teams": {"P": {"off": 6.0, "def": 4.0}}}
    r = orr.fit_ratings([], as_of=T0, lam=5.0, prior=prior, rho=0.5)
    assert r["teams"]["P"]["off"] == pytest.approx(3.0)
    assert r["teams"]["P"]["def"] == pytest.approx(2.0)


def test_home_field_and_neutral():
    r = orr.fit_ratings(_league(), as_of=T0 + timedelta(days=60), lam=2.0)
    h, a = orr.predict(r, "S1", "S2")
    hn, an = orr.predict(r, "S1", "S2", neutral=True)
    assert (h - a) - (hn - an) == pytest.approx(r["hfa"])


def test_labels():
    r = orr.fit_ratings([], as_of=T0, lam=5.0)
    assert r["status_label"] == "SCREEN" and r["validation"] == "NOT_VALIDATED"


def _ctx(**kw):
    c = {k: 0.0 for k in CONTEXT_KEYS["CFB"]}
    c.update(kw)
    return c


def test_engine_uses_opponent_adjusted_composition_and_stays_ml_consistent():
    from artifacts.free_models import CFB_OPP_MODEL as C
    c = _ctx(cfb_opp_adjusted=1.0, cfb_league_mean_pts=27.0, cfb_hfa=3.0,
             home_off_rating=6.0, home_def_rating=-2.0,
             away_off_rating=1.0, away_def_rating=4.0, home_rating=0.0, away_rating=0.0)
    hm, am = score_means("CFB", c)
    # raw ridge points = league mean + HFA/2 + own offense - opponent defense
    rh, ra = 27.0 + 1.5 + 6.0 - 4.0, 27.0 - 1.5 + 1.0 + 2.0
    # then the 2024-fit linear recalibration of margin and total
    m = C["margin_intercept"] + C["margin_slope"] * (rh - ra)
    t = C["total_intercept"] + C["total_slope"] * (rh + ra)
    assert hm == pytest.approx(t / 2 + m / 2)
    assert am == pytest.approx(t / 2 - m / 2)
    p, _ = model_probability("CFB", "ML", "HOME", None, hm, am)
    sd = PRIORS["CFB"][2]
    assert p == pytest.approx(0.5 * (1 + math.erf((hm - am) / sd / math.sqrt(2))))


def test_live_ratings_from_scoreboards_strictly_before_kickoff():
    kick = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)
    def ev(eid, date, h, a, hs, as_, done=True):
        return {"id": eid, "date": date, "competitions": [{"neutralSite": False,
                "status": {"type": {"completed": done}},
                "competitors": [{"homeAway": "home", "team": {"id": h}, "score": str(hs)},
                                {"homeAway": "away", "team": {"id": a}, "score": str(as_)}]}]}
    boards = {2025: [ev("1", "2025-10-01T16:00Z", "10", "20", 35, 10)],
              2026: [ev("2", "2026-10-17T16:00Z", "10", "20", 40, 7),
                     ev("3", "2026-10-24T16:00Z", "10", "20", 0, 70),     # the game itself
                     ev("4", "2026-10-25T16:00Z", "10", "20", 0, 70, False)]}
    def fetch(url):
        season = 2025 if "dates=2025" in url else 2026
        return {"events": boards[season] if "week=1&" in url and "seasontype=2" in url else []}
    r = orr.live_ratings(fetch, kick)
    assert r["n_games"] == 1
    assert r["teams"]["10"]["off"] > r["teams"]["20"]["off"]


def test_engine_fallback_without_flag_unchanged():
    c = _ctx(home_total_rating=50.0, away_total_rating=50.0, home_rating=3.0)
    c2 = dict(c, home_off_rating=99.0, away_def_rating=99.0)  # ignored without flag
    assert score_means("CFB", c) == score_means("CFB", c2)
