"""t272: CFB margin compression fix + auditor L2/L4 (SCREEN, NOT_VALIDATED)."""
import math
from datetime import datetime, timedelta, timezone

from artifacts import free_models as fm
from artifacts.free_models import CONTEXT_KEYS, PRIORS, model_probability, score_means


def _ctx(sport, **kw):
    c = {k: 0.0 for k in CONTEXT_KEYS[sport]}
    c.update(kw)
    return c


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _sample(margins, totals=None):
    t0 = datetime(2026, 10, 18, tzinfo=timezone.utc)
    totals = totals or [56.0] * len(margins)
    out = []
    for i, (m, t) in enumerate(zip(margins, totals)):
        pf = (t + m) / 2
        out.append((t0 - timedelta(days=7 * i), pf, t - pf))
    return out


def test_cfb_rating_not_compressed():
    strong = fm.cfb_ratings_from_sample(_sample([30, 28, 35, 25, 32]))
    weak = fm.cfb_ratings_from_sample(_sample([-10, -7, -14, -3, -11]))
    hm, am = score_means("CFB", _ctx("CFB", home_rating=strong["rating"],
                                     away_rating=weak["rating"],
                                     home_total_rating=strong["total_rating"],
                                     away_total_rating=weak["total_rating"]))
    # 39-point average-margin gap must project well beyond the old ~8.5 cap
    assert hm - am > 18


def test_cfb_margin_consistent_with_own_moneyline():
    for hr, ar in ((8.0, -6.0), (-4.0, 3.0), (0.0, 0.0), (15.0, -9.0)):
        c = _ctx("CFB", home_rating=hr, away_rating=ar,
                 home_total_rating=55.0, away_total_rating=55.0)
        hm, am = score_means("CFB", c)
        margin = hm - am
        sd = PRIORS["CFB"][2]
        p_ml, _ = model_probability("CFB", "ML", "HOME", None, hm, am)
        assert abs(p_ml - _phi(margin / sd)) < 1e-9
        # the spread at the model's own margin must be a coin flip
        p_cover, _ = model_probability("CFB", "SPREAD", "HOME", -margin + 1e-6 + 0.0, hm, am)
        assert abs(p_cover - 0.5) < 0.01
        # ML favourite iff projected margin > 0
        assert (p_ml > 0.5) == (margin > 0) or margin == 0


def test_cfb_total_not_driven_by_margin_ratings():
    a = score_means("CFB", _ctx("CFB", home_rating=12.0, away_rating=10.0,
                                home_total_rating=50.0, away_total_rating=50.0))
    b = score_means("CFB", _ctx("CFB", home_rating=-12.0, away_rating=-10.0,
                                home_total_rating=50.0, away_total_rating=50.0))
    assert abs(sum(a) - sum(b)) < 1e-9


def test_cfb_total_tracks_scoring_environment():
    lo = sum(score_means("CFB", _ctx("CFB", home_total_rating=42.0, away_total_rating=44.0)))
    hi = sum(score_means("CFB", _ctx("CFB", home_total_rating=68.0, away_total_rating=70.0)))
    assert hi - lo > 10


def test_cfb_missing_total_history_uses_league_mean_not_zero():
    t = sum(score_means("CFB", _ctx("CFB")))
    assert 50 <= t <= 58


def test_nfl_unchanged():
    hm, am = score_means("NFL", _ctx("NFL", home_rating=2.0, away_rating=-1.0))
    base, _, _, hfa = PRIORS["NFL"]
    assert (hm, am) == (base + hfa / 2 + 2.0, base - hfa / 2 - 1.0)


def test_cfb_engine_family_stays_unvalidated():
    assert fm.CFB_MARGIN_MODEL["validation"] == "NOT_VALIDATED"
    assert fm.CFB_MARGIN_MODEL["status_label"] == "SCREEN"


# ---- L4: quote freshness re-checked at pricing time ----
def test_calculate_rechecks_freshness_with_pricing_clock():
    t = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
    row = {"sport": "NFL", "away": "A", "home": "B", "market": "SPREAD",
           "side": "HOME", "line": -3.5, "odds": -110,
           "kickoff": "2026-10-25T17:00:00Z",
           "quote_captured_at": (t - timedelta(seconds=10)).isoformat()}
    fresh = fm.calculate(dict(row), None, t, auto_context=False)
    assert fresh["quote_freshness"]["code"] == "QUOTE_FRESH_UNDER_180S"
    stale = fm.calculate(dict(row), None, t, auto_context=False,
                         freshness_clock=lambda: t + timedelta(seconds=400))
    assert stale["quote_freshness"]["code"] != "QUOTE_FRESH_UNDER_180S"
    assert stale["quote_freshness"]["age_seconds"] >= 400


def test_run_live_freshness_uses_wall_clock(monkeypatch):
    seen = {}
    real = fm.calculate

    def spy(*a, **k):
        seen["clock"] = k.get("freshness_clock")
        return real(*a, **k)
    monkeypatch.setattr(fm, "calculate", spy)
    t = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
    fm.run({"lines": [{"sport": "NFL", "away": "A", "home": "B", "market": "ML",
                       "side": "HOME", "odds": -110, "kickoff": "2026-10-25T17:00:00Z",
                       "quote_captured_at": t.isoformat()}]},
           now=t, auto_context=False, live_freshness=True)
    assert callable(seen["clock"])
    fm.run({"lines": [{"sport": "NFL", "away": "A", "home": "B", "market": "ML",
                       "side": "HOME", "odds": -110, "kickoff": "2026-10-25T17:00:00Z",
                       "quote_captured_at": t.isoformat()}]},
           now=t, auto_context=False)
    assert seen["clock"] is None
