"""NFL_ENTRY_FORM_V2 construction tests (DESIGN stage — NOT FROZEN).

Includes the FREEZE-BLOCKING fireability test from PREREG_DRAFT §3/§7:
at the pinned sigma per market, Phi(3.0/sigma) >= 0.545 and
Phi(5.0/sigma) >= 0.60. If either assertion ever fails there is no
freeze — the exact assertion whose absence let the retired construction
ship a pick rule that could never fire.
"""
import math
from statistics import NormalDist

import pytest

from sportsedge import nfl_entry_form_v2 as efv2
from sportsedge import nfl_entry_form_v2_constants as C

ND = NormalDist()


def make_feat(**over):
    feat = {
        "x_epa_margin": 0.0, "x_form_margin": 0.0, "x_qb_h": 0.0,
        "x_qb_a": 0.0, "x_rest": 0.0, "y_epa_total": 0.0, "y_form_total": 0.0,
        "y_pace": 124.0, "y_pace_dev": 0.0, "y_wind": 0.0, "y_cold": 0.0,
        "home_prior_games": 8, "away_prior_games": 8,
        "home_starter_known": True, "away_starter_known": True,
    }
    feat.update(over)
    return feat


def quote(line=0.0, first=-110, second=-110):
    return efv2.EntryQuote(line=line, price_first=first, price_second=second,
                           captured_at="2025-11-09T17:00:00+00:00")


# ---------------------------------------------------------------------------
# Fireability (FREEZE-BLOCKING, PREREG_DRAFT §3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("market", ["SPREAD", "TOTAL"])
def test_fireability_at_pinned_sigma(market):
    sigma = C.SIGMA_FIT[market]
    assert sigma >= C.SIGMA_FLOOR
    # The two assertions the freeze checklist (§7.3) demands.
    assert efv2.stated_probability(3.0, market) >= 0.545
    assert efv2.stated_probability(5.0, market) >= 0.60
    # Equivalent crossing statement: p >= 0.545 is reached at
    # |d| = sigma * Phi^-1(0.545) ~= 0.113 sigma, below the 3.0 gate.
    assert ND.inv_cdf(0.545) * sigma <= 3.0


def test_probability_map_raw_and_uncapped():
    # No shrink, no cap: the map is Phi(|d|/sigma) exactly, and huge
    # deviations approach 1 (the retired map capped stated p at ~0.519).
    for market in ("SPREAD", "TOTAL"):
        sigma = C.SIGMA_FIT[market]
        assert efv2.stated_probability(3.0, market) == \
            pytest.approx(efv2.norm_cdf(3.0 / sigma))
        assert efv2.stated_probability(40.0, market) > 0.99
        assert efv2.stated_probability(6.0, market) > \
            efv2.stated_probability(3.0, market)


def test_projection_never_touches_a_line():
    # Defect-1/2 fix: the projection is a function of features only.
    feat = make_feat(x_epa_margin=25.0, x_form_margin=4.0,
                     y_epa_total=44.0, y_form_total=3.0)
    p1 = efv2.project_margin(feat)
    rec_a = efv2.decide_market("SPREAD", p1, 1.0, quote(line=0.0), feat,
                               game_id="G")
    rec_b = efv2.decide_market("SPREAD", p1, 1.0, quote(line=-13.5), feat,
                               game_id="G")
    assert rec_a["projection"] == rec_b["projection"] == p1
    assert rec_a["d"] != rec_b["d"]  # only the deviation moves


# ---------------------------------------------------------------------------
# EPA books (DESIGN §4.1)
# ---------------------------------------------------------------------------

def line(team, epa, plays_att=30, sacks=3, carries=27, pass_epa=None):
    return efv2.TeamWeekLine(
        team=team, passing_epa=epa if pass_epa is None else pass_epa,
        rushing_epa=0.0, attempts=plays_att, sacks_suffered=sacks,
        carries=carries)


def test_shrinkage_prior_250():
    books = efv2.EPABooks()
    books.roll_season()
    books.add_game(line("H", 6.0), line("A", -6.0))
    off, dfn, pace, games = books.rates("H")
    assert games == 1
    assert off == pytest.approx(6.0 / (60.0 + 250.0))
    assert dfn == pytest.approx(-6.0 / (60.0 + 250.0))  # opp's off sums
    assert pace == pytest.approx(60.0)


def test_prior_season_carry_030_and_games_reset():
    books = efv2.EPABooks()
    books.roll_season()
    books.add_game(line("H", 6.0), line("A", -6.0))
    books.roll_season(books.final())
    off, _, _, games = books.rates("H")
    assert games == 0  # eligibility is in-season (PREREG §3)
    assert off == pytest.approx((6.0 * 0.30) / (60.0 * 0.30 + 250.0))


def test_form_blend_150_prior_toward_season():
    books = efv2.EPABooks()
    books.roll_season()
    for _ in range(4):
        books.add_game(line("H", 6.0), line("A", 0.0))
    season_off, _, _, _ = books.rates("H")
    form_off, _ = books.form_rates("H")
    # last-4 = all four games: form shrinks their sums toward the season rate
    assert form_off == pytest.approx((24.0 + 150.0 * season_off) / (240.0 + 150.0))


def test_features_use_prior_games_only():
    books = efv2.EPABooks()
    qb = efv2.QBBook()
    books.roll_season()
    qb.roll_season()
    ctx = efv2.GameContext(game_id="G1", home_team="H", away_team="A",
                           home_starter_known=True, away_starter_known=True)
    before = efv2.build_features(books, qb, ctx)
    books.add_game(line("H", 30.0), line("A", 0.0))
    books.add_game(line("H", 30.0), line("B", 0.0))
    after = efv2.build_features(books, qb, ctx)
    assert before["x_epa_margin"] != after["x_epa_margin"]
    assert before["home_prior_games"] == 0 and after["home_prior_games"] == 2


def test_qb_delta_scale_and_shrinkage():
    qb = efv2.QBBook()
    qb.roll_season()
    qb.add_game("T", [efv2.QBWeekLine("S1", 100, 30.0, 0.0),
                      efv2.QBWeekLine("S2", 50, 0.0, 0.0)])
    starter_rate = 30.0 / (100.0 + 200.0)
    team_rate = 30.0 / (150.0 + 200.0)
    assert qb.delta("T", "S1") == pytest.approx((starter_rate - team_rate) * 36.0)
    assert qb.delta("T", None) == 0.0  # unknown starter: no veto feature


# ---------------------------------------------------------------------------
# Pick rule (PREREG_DRAFT §3)
# ---------------------------------------------------------------------------

def test_pick_happy_path():
    rec = efv2.decide_market("SPREAD", 10.0, 1.5, quote(line=0.0),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PICK"
    assert rec["selected_side"] == "HOME"
    assert rec["picked_price"] == -110
    assert rec["pass_reason"] is None
    assert rec["counted"] is False and rec["verified_play"] is False


def test_agreement_veto_blocks_lone_signal():
    rec = efv2.decide_market("SPREAD", 10.0, -0.5, quote(line=0.0),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_AGREEMENT_VETO


def test_zero_adjustment_vetoes():
    rec = efv2.decide_market("TOTAL", 55.0, 0.0, quote(line=44.0),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_AGREEMENT_VETO


def test_distance_gate():
    rec = efv2.decide_market("SPREAD", 2.99, 1.0, quote(line=0.0),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_DISTANCE


def test_probability_gate_with_inflated_sigma(monkeypatch):
    # With the pinned sigma the probability gate cannot bind inside the
    # distance gate (that is the fireability property); inflate sigma to
    # prove the gate itself fires when the map cannot reach 0.545.
    monkeypatch.setitem(C.SIGMA_FIT, "SPREAD", 40.0)
    rec = efv2.decide_market("SPREAD", 3.5, 1.0, quote(line=0.0),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_PROBABILITY


def test_price_cap():
    capped = efv2.decide_market("SPREAD", 10.0, 1.0,
                                quote(line=0.0, first=-170), make_feat(),
                                game_id="G")
    assert capped["decision"] == "PASS"
    assert capped["pass_reason"] == efv2.PASS_PRICE_CAP
    at_cap = efv2.decide_market("SPREAD", 10.0, 1.0,
                                quote(line=0.0, first=-165), make_feat(),
                                game_id="G")
    assert at_cap["decision"] == "PICK"  # >= -165 is allowed (§3)


def test_starter_state_must_be_known():
    rec = efv2.decide_market("SPREAD", 10.0, 1.0, quote(line=0.0),
                             make_feat(away_starter_known=False), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_STARTER_UNKNOWN


def test_eligibility_gate():
    rec = efv2.decide_market("TOTAL", 60.0, 2.0, quote(line=44.0),
                             make_feat(home_prior_games=2), game_id="G")
    assert rec["decision"] == "PASS"
    assert rec["pass_reason"] == efv2.PASS_ELIGIBILITY


def test_totals_pick_side_and_price():
    rec = efv2.decide_market("TOTAL", 40.0, -1.0,
                             quote(line=47.5, first=-115, second=-105),
                             make_feat(), game_id="G")
    assert rec["decision"] == "PICK"
    assert rec["selected_side"] == "UNDER"
    assert rec["picked_price"] == -105


# ---------------------------------------------------------------------------
# Constants traceability (PREREG_DRAFT §7.4 / DESIGN §4)
# ---------------------------------------------------------------------------

def test_constants_match_prereg_values():
    assert C.PRIOR_PLAYS == 250.0
    assert C.FORM_PRIOR_PLAYS == 150.0
    assert C.FORM_WINDOW_GAMES == 4
    assert C.CARRY_TEAM == 0.30
    assert C.CARRY_QB == 0.50
    assert C.PRIOR_QB_ATTEMPTS == 200.0
    assert C.MIN_PRIOR_REG_GAMES == 3
    assert C.DISTANCE_GATE == 3.0
    assert C.PROBABILITY_GATE == 0.545
    assert C.PRICE_CAP == -165
    assert C.SIGMA_FLOOR == 12.5
    for market in ("SPREAD", "TOTAL"):
        assert C.SIGMA_FIT[market] == max(C.SIGMA_FIT_RAW[market], 12.5)
        assert set(C.CORE_FIT[market]) >= {"intercept", "form_divergence"}
        assert math.isfinite(C.SIGMA_FIT[market]) and C.SIGMA_FIT[market] > 0
