"""CFB first-half moneyline engine: probabilities from the SAME 1H margin
distribution the 1H spread pricer uses, tie mass as an explicit push.

The margin model is continuous, so the mass on an exactly-tied half is
the codebase's continuity-corrected integer mass (the (-0.5, +0.5]
margin band), identical to the convention _normal_outcome applies to
integer SPREAD_1H lines. Push handling downstream is the research
bridge's existing two-way convention: loss = 1 - win - push, and fair
odds are computed on the conditional probability win / (1 - push).

Fake scoring tuples only (pure math / contract tests), mirroring
tests/test_team_half_verified_research.py.
"""
from datetime import datetime, timezone
from math import erf, sqrt
from unittest.mock import patch

import sportsedge.team_half_pricing as derivative

NOW = datetime(2026, 10, 11, 20, 30, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T00:00:00Z"
NOTES = ["HOME_HISTORY_COUNT:5", "AWAY_HISTORY_COUNT:5",
         "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
         "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
         "WEATHER:INDOOR_VERIFIED"]


def scoring(hm=24., am=20., sd_t=13.5, sd_m=13.7):
    return (hm, am, sd_t, sd_m,
            datetime(2026, 10, 12, tzinfo=timezone.utc), NOTES, "401999001")


def row(side="HOME", odds=-110, sport="CFB", market="ML_1H", **extra):
    base = {"sport": sport, "away": "Delaware", "home": "Middle Tennessee",
            "kickoff": KICKOFF, "team": "", "side": side,
            "market": market, "odds": odds, "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:29:00Z"}
    base.update(extra)
    return base


def pair(**kw):
    return [row(side="HOME", **kw), row(side="AWAY", **kw)]


def priced(rows, raw=None):
    with patch.object(derivative, "_scoring", return_value=raw or scoring()):
        return derivative.price_team_half_rows(rows, now=NOW)[0]


def phi(z):
    return 0.5 * (1 + erf(z / sqrt(2)))


def expected_win_push(hm, am, sd_m, side):
    """Independent erf computation of the 1H margin masses at scale 0.50."""
    mean = (hm - am) * 0.5 if side == "HOME" else (am - hm) * 0.5
    sd = sd_m * sqrt(0.5)
    win = 1 - phi((0.5 - mean) / sd)
    push = phi((0.5 - mean) / sd) - phi((-0.5 - mean) / sd)
    return win, push


def test_ml_1h_is_a_priced_derivative_family():
    assert "ML_1H" in derivative.DERIVATIVES
    assert "ML_1H" in derivative.PERIOD_MARKETS
    assert "ML_1H" not in derivative.TEAM_MARKETS


def test_ml_1h_pair_prices_from_the_margin_distribution():
    out = priced(pair())
    assert len(out) == 2
    assert all(x["status"] != "NO_MODEL_OR_MARKET" for x in out)
    # Period markets stay unfitted research WATCH even with an edge: the
    # positive-EV side is relabeled off RESEARCH_CANDIDATE_NOT_VALIDATED,
    # the negative-EV side keeps its bridge WATCH reason.
    assert all(x["status"] != "RESEARCH_CANDIDATE_NOT_VALIDATED" for x in out)
    assert out[0]["status"] == "WATCH_UNFITTED_PERIOD_SPLIT"
    assert out[1]["status"] == "WATCH_BELOW_EV_FLOOR"
    assert all(x["score_period_fraction"] == 0.5 for x in out)
    assert all(x["source"] == "FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED" for x in out)
    assert all(x["dk_no_vig_p"] == 0.5 for x in out)  # -110 / -110
    assert all(x["line"] is None for x in out)  # a moneyline has no line
    home, away = out[0], out[1]
    assert home["selection"] == "HOME" and away["selection"] == "AWAY"
    for got, side in ((home, "HOME"), (away, "AWAY")):
        win, push = expected_win_push(24., 20., 13.7, side)
        assert abs(got["model_probability"] - round(win, 6)) < 2e-6
        assert abs(got["model_push_p"] - round(push, 6)) < 2e-6
        cond = win / (1 - push)
        assert abs(got["model_conditional_p"] - round(cond, 6)) < 2e-6


def test_ml_1h_home_away_push_masses_mirror_exactly():
    out = priced(pair())
    home, away = out[0], out[1]
    assert home["model_push_p"] == away["model_push_p"]
    total = home["model_probability"] + away["model_probability"] + home["model_push_p"]
    assert abs(total - 1.0) < 2e-6
    assert home["model_push_p"] > 0  # an integer margin band carries mass


def test_ml_1h_fat_tie_mass_for_even_teams():
    out = priced(pair(), raw=scoring(hm=21., am=21., sd_m=2.0))
    home, away = out[0], out[1]
    sd = 2.0 * sqrt(0.5)
    push_expected = 2 * phi(0.5 / sd) - 1
    assert push_expected > 0.25  # the fat-tie case: >25% of mass on a tie
    assert abs(home["model_push_p"] - push_expected) < 2e-6
    assert home["model_probability"] == away["model_probability"]
    assert abs(home["model_probability"] - (1 - push_expected) / 2) < 2e-6


def test_ml_1h_push_mass_is_neither_won_nor_lost_in_ev():
    # Even teams at +100/+100: conditional p is exactly 0.5, so EV is
    # exactly zero ONLY if the tie mass is excluded from the loss term
    # (loss = 1 - win - push). Treating a tied half as a loss would
    # produce ev_per_dollar == -push.
    rows = [row(side="HOME", odds=100), row(side="AWAY", odds=100)]
    out = priced(rows, raw=scoring(hm=21., am=21., sd_m=2.0))
    assert all(x["status"] != "NO_MODEL_OR_MARKET" for x in out)
    assert all(abs(x["ev_per_dollar"]) < 1e-6 for x in out)
    assert all(x["fair_american"] in (-100, 100) for x in out)


def test_ml_1h_unpaired_quote_never_prices():
    out = priced([row(side="HOME")])
    assert out[0]["status"] == "NO_MODEL_OR_MARKET"
    assert "EXACT_PAIRED_DK_QUOTE_REQUIRED" in out[0]["reason"]


def test_ml_1h_degenerate_margin_distribution_refused():
    for bad_sd in (0.0, -3.0, float("nan")):
        out = priced(pair(), raw=scoring(sd_m=bad_sd))
        assert all(x["status"] == "NO_MODEL_OR_MARKET" for x in out), bad_sd
        assert all("NONFINITE_DERIVATIVE_DISTRIBUTION" in x["reason"]
                   for x in out), bad_sd


def test_ml_1h_degenerate_probability_refused():
    # A mean so extreme that the win mass saturates to exactly 1.0 in
    # float is a degenerate distribution, not a price.
    out = priced(pair(), raw=scoring(hm=400., am=0.))
    assert all(x["status"] == "NO_MODEL_OR_MARKET" for x in out)
    assert all("DERIVATIVE_PROBABILITY_NOT_CALIBRATED_OR_DEGENERATE" in x["reason"]
               for x in out)


def test_ml_1h_nonzero_line_fails_closed_and_zero_line_is_no_line():
    bad = priced([row(side="HOME", line=2.5), row(side="AWAY", line=2.5)])
    assert all(x["status"] == "NO_MODEL_OR_MARKET" for x in bad)
    assert all("MONEYLINE_LINE_NOT_APPLICABLE" in x["reason"] for x in bad)
    # An explicit zero line is the same no-line state as an absent line,
    # and the two shapes pair with each other.
    mixed = priced([row(side="HOME", line=0), row(side="AWAY")])
    assert all(x["status"] != "NO_MODEL_OR_MARKET" for x in mixed)


def test_ml_1h_is_football_only_and_nfl_prices_symmetrically():
    mlb = priced(pair(sport="MLB"))
    assert all(x["status"] == "NO_MODEL_OR_MARKET" for x in mlb)
    assert all("FOOTBALL_FIRST_HALF_ONLY" in x["reason"] for x in mlb)
    nfl = priced(pair(sport="NFL"))
    assert all(x["status"] != "NO_MODEL_OR_MARKET" for x in nfl)


def test_ml_1h_upstream_gate_still_precedes_the_engine():
    with patch.object(derivative, "_scoring",
                      side_effect=ValueError("PUBLIC_TEAM_INJURY_FEED_UNVERIFIED")):
        out = derivative.price_team_half_rows(pair(), now=NOW)[0]
    assert all(x["status"] == "NO_MODEL_OR_MARKET" for x in out)
    assert all(x["reason"] == "PUBLIC_TEAM_INJURY_FEED_UNVERIFIED" for x in out)
