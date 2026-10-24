"""t273 audit fixes: calibrated CFB spread/total probabilities on the card,
FBS-only home field, fail-closed live rating fetch. SCREEN / NOT_VALIDATED."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from artifacts import free_models as fm
from sportsedge.sports.cfb import opponent_ratings as orr

T0 = datetime(2025, 9, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
KICK = NOW + timedelta(hours=14)


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---- 1. calibrated card probabilities ----
def _ctx(home_off=12.0):
    c = {k: 0.0 for k in fm.CONTEXT_KEYS["CFB"]}
    c.update(cfb_opp_adjusted=1.0, cfb_league_mean_pts=27.0, cfb_hfa=3.0,
             home_off_rating=home_off, home_total_rating=55.0, away_total_rating=55.0)
    return c


def _row(market, side, line, odds=-110):
    return {"sport": "CFB", "away": "Away St", "home": "Home U", "market": market,
            "side": side, "line": line, "odds": odds, "kickoff": KICK.isoformat(),
            "quote_captured_at": NOW.isoformat()}


@pytest.fixture
def opp(monkeypatch):
    monkeypatch.setattr(fm, "context_for",
                        lambda *a, **k: (_ctx(), KICK, ["HOME_CFB_OPP_ADJUSTED_RATING",
                                                        "AWAY_CFB_OPP_ADJUSTED_RATING"]))


def test_constants_fitted_sd_and_beta():
    c = fm.CFB_OPP_MODEL
    assert 0 <= c["beta_spread"] <= 1 and 0 <= c["beta_total"] <= 1
    assert c["sd_margin"] == c["sd_margin_2024"] and c["sd_total"] == c["sd_total_2024"]
    assert c["beta_fit_uses_2024_closing_lines"] is True


def test_spread_card_uses_calibrated_probability(opp):
    r = fm.calculate(_row("SPREAD", "HOME", -3.5), None, NOW)
    la = r["pricing_lanes"]["lane_a_independent"]
    hm, am = fm.score_means("CFB", _ctx())
    c = fm.CFB_OPP_MODEL
    z = ((hm - am) - 3.5) / c["sd_margin"]
    assert la["estimate_p"] == pytest.approx(_phi(c["beta_spread"] * z), abs=1e-6)
    assert la["raw_estimate_p"] == pytest.approx(_phi(z), abs=1e-6)
    assert la["probability_basis"] == "CFB_CALIBRATED_2024_BETA_TOWARD_LINE"
    assert r["estimate_p"] == la["estimate_p"]


def test_total_card_uses_calibrated_probability(opp):
    r = fm.calculate(_row("TOTAL", "OVER", 48.5), None, NOW)
    la = r["pricing_lanes"]["lane_a_independent"]
    hm, am = fm.score_means("CFB", _ctx())
    c = fm.CFB_OPP_MODEL
    z = ((hm + am) - 48.5) / c["sd_total"]
    assert la["estimate_p"] == pytest.approx(_phi(c["beta_total"] * z), abs=1e-6)


def test_big_raw_gap_is_not_a_candidate_after_calibration(opp, monkeypatch):
    monkeypatch.setattr(fm, "context_for",
                        lambda *a, **k: (_ctx(home_off=30.0), KICK, []))
    r = fm.calculate(_row("SPREAD", "HOME", -3.5), None, NOW)
    la = r["pricing_lanes"]["lane_a_independent"]
    assert la["raw_estimate_p"] > 0.8
    if fm.CFB_OPP_MODEL["beta_spread"] < 0.1:
        assert la["ev_per_dollar"] < 0.02


def test_moneyline_raw_but_labelled_worse_than_market(opp):
    r = fm.calculate(_row("ML", "HOME", None, odds=-150), None, NOW)
    la = r["pricing_lanes"]["lane_a_independent"]
    hm, am = fm.score_means("CFB", _ctx())
    assert la["estimate_p"] == pytest.approx(_phi((hm - am) / fm.CFB_OPP_MODEL["sd_margin"]), abs=1e-6)
    lab = la["oos_2025_vs_market"]
    assert lab["verdict"] == "WORSE_THAN_MARKET"
    assert lab["model_brier"] > lab["market_no_vig_brier"]


# ---- 2. FBS-only home field ----
def g(day, home, away, hs, as_, fbs_both=True, neutral=False):
    return {"date": (T0 + timedelta(days=day)).isoformat(), "home": home, "away": away,
            "hs": float(hs), "as": float(as_), "neutral": neutral, "fbs_both": fbs_both}


def test_hfa_fit_on_fbs_vs_fbs_only():
    games = []
    teams = ["A", "B", "C", "D"]
    d = 0
    for i in range(6):
        for h in teams:
            for a in teams:
                if h != a:
                    games.append(g(d, h, a, 27 + 3, 27 - 0))  # true FBS HFA = 3
        for h in teams:
            games.append(g(d + 1, h, "FCS" + str(i), 52, 3, fbs_both=False))
        d += 7
    r = orr.fit_ratings(games, as_of=T0 + timedelta(days=60), lam=1.0, lam_hfa=0.01)
    assert r["hfa"] == pytest.approx(3.0, abs=0.75)
    assert "hfa_non_fbs" in r


# ---- 3. fail-closed live fetch ----
def test_any_week_fetch_failure_refuses_ratings():
    def fetch(url):
        if "week=5&" in url and "dates=2026" in url:
            return None
        return {"events": []}
    with pytest.raises(ValueError, match="CFB_RATINGS_FETCH_INCOMPLETE"):
        orr.live_ratings(fetch, KICK)


def test_engine_falls_back_to_t272_on_partial_fetch():
    class P:
        def fetch(self, url):
            return None if "week=3&" in url else {"events": []}
    assert fm._cfb_opp_ratings(P(), KICK) is None
