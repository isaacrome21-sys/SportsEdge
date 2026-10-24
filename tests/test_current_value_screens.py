"""Current-price screens are separate from proof of long-term model quality."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sportsedge.handicap_explanations import handicap_explanation
from sportsedge.phone_display import build_current_value_screens, render_phone_card
from sportsedge.quote_freshness import QUOTE_FRESH, QUOTE_STALE


AS_OF = "2026-10-23T22:00:00Z"
KICKOFF = "2026-10-23T23:00:00Z"
NOW = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)


def screen(c):
    return build_current_value_screens(c, now=NOW)


def row(**overrides):
    data = {
        "sport": "MLB", "market": "PITCHER_K", "selection": "UNDER",
        "status": "RESEARCH_CANDIDATE_NOT_VALIDATED", "game": "Away @ Home",
        "player_name": "Player", "line": 4.5, "dk_odds": -120,
        "model_probability": .63, "ev_per_dollar": .155,
        "pricing_provenance": {"lane": "INDEPENDENT"},
        "quote_freshness": {"code": QUOTE_FRESH, "age_seconds": 30},
        "kickoff_utc": KICKOFF,
    }
    data.update(overrides)
    return data


def card(*rows):
    return {"as_of_utc": AS_OF, "evaluated_rows": list(rows),
            "summary": {"rows": len(rows)}, "min_ev": .02}


@pytest.mark.parametrize("sport,market", [
    ("MLB", "PITCHER_K"), ("NBA", "PLAYER_POINTS"),
    ("CFB", "TOTAL"), ("NFL", "PASSING_YARDS"),
    ("NHL", "GOALIE_SAVES"), ("CBB", "TEAM_TOTAL"),
    ("UFC", "METHOD_OF_VICTORY"), ("PGA", "MATCHUP"),
])
def test_current_numbers_screen_every_sport_and_market_without_long_term_gate(sport, market):
    extra = {}
    if sport in {"CFB", "NFL"}:
        # Oct 24 2026 rulings: CFB and NFL screens require the market blend.
        extra["pricing_lanes"] = {"lane_b_anchored": {
            "estimate_p": .63, "ev_per_dollar": .155, "fair_american": -170}}
    data = card(row(sport=sport, market=market, **extra))
    result = screen(data)
    assert result["historical_tests_required_to_display"] is False
    assert result["total_positive_screens"] == 1
    pick = result["unverified_model_value_screens"][0]
    assert pick["sport"] == sport and pick["market"] == market
    assert pick["model_estimate_p"] == .63
    assert pick["book_raw_breakeven_p"] == round(120 / 220, 6)
    assert pick["raw_estimated_ev"] == pytest.approx(.155)
    assert pick["ev_repriced_at_current_quote"] is True
    assert pick["research_playable_to"] == -165
    assert pick["status"] == "CURRENT_MODEL_VALUE_SCREEN_NOT_VERIFIED_PLAY"
    assert pick["can_be_official_play"] is False
    assert result["verified_plays"] == 0


def test_estimated_value_ranking_and_explanations_on_phone_card():
    r1 = row(model_probability=.58, ev_per_dollar=.05)
    r2 = row(model_probability=.64, ev_per_dollar=.16, player_name="Nick Martinez")
    c = card(r1, r2)
    h = handicap_explanation({**r2, "handicap_factors": [
        {"name": "prior-start strikeouts", "value": 2.9,
         "source": "MLB StatsAPI", "direction": "SUPPORTS"}]})
    c["handicap_explanations"] = [
        {"input_index": 0, **handicap_explanation(r1)},
        {"input_index": 1, **h},
    ]
    before = deepcopy(c)
    result = screen(c)
    assert result["total_positive_screens"] == 2
    assert result["unverified_model_value_screens"][0]["player_name"] == "Nick Martinez"
    assert result["unverified_model_value_screens"][0]["supporting_factors"][0]["name"] == "prior-start strikeouts"
    output = render_phone_card(c, now=NOW)
    assert "Current priced value screens" in output
    assert "Nick Martinez" in output and "prior-start strikeouts" in output
    assert "Verified PLAYs: 0" in output
    assert c == before


@pytest.mark.parametrize("blocked,reason", [
    ({"quote_freshness": {"code": QUOTE_STALE}}, "NO_VERIFIED_CURRENT_QUOTE"),
    ({"pricing_provenance": {"lane": "MARKET_ANCHORED"}}, "NO_INDEPENDENT_PROJECTION"),
    ({"dk_odds": -170}, "MISSING_QUOTE_OR_PRICE_CAP"),
    ({"kickoff_utc": "2026-10-23T21:00:00Z"}, "PREGAME_CLOCK_UNVERIFIED_OR_STARTED"),
    ({"model_probability": .50}, "NO_POSITIVE_ESTIMATED_EV"),
    ({"model_probability": None}, "NO_MODEL_PROBABILITY"),
    ({"status": "BLOCKED_IL_COLLEGE"}, "BLOCKED_OR_UNPRICED"),
    ({"status": "PLAY"}, "NONCANONICAL_RESEARCH_PRICE_STATUS"),
    ({"independent_projection": {"estimate_p": .8, "ev_per_dollar": .1,
                                  "paired_market_status": "MISSING_EXACT_OPPOSITE_DK_PRICE"}},
     "OPPOSITE_SIDE_QUOTE_NOT_VERIFIED"),
    ({"context_notes": ["NO_FETCH_MANUAL_MODE"]}, "LIVE_CONTEXT_NOT_VERIFIED"),
])
def test_fail_closed_on_wrong_quote_context_and_authority(blocked, reason):
    result = screen(card(row(**blocked)))
    assert result["total_positive_screens"] == 0
    assert result["exclusions"][reason] == 1


def test_no_quote_is_not_an_edge_and_no_invented_pitch_to_contact():
    result = screen(card(row(quote_freshness=None)))
    assert result["unverified_model_value_screens"] == []
    assert "pitch to contact" not in render_phone_card(card(row()), now=NOW).lower()


def test_moved_price_recomputes_ev_instead_of_trusting_old_reported_ev():
    # An earlier +15.5% estimate can become negative after a price change.
    result = screen(card(row(dk_odds=-165)))
    assert result["total_positive_screens"] == 1
    pick = result["unverified_model_value_screens"][0]
    assert pick["raw_estimated_ev"] == pytest.approx(.63 * (1 + 100 / 165) - 1)
    assert pick["prior_ev_differs_from_current_quote"] is True
    # If the same model p were 60%, that changed price is now -3.6% EV.
    assert screen(card(row(dk_odds=-165,
                           model_probability=.6)))["total_positive_screens"] == 0


def test_status_pass_from_old_quote_cannot_hide_new_positive_market_price():
    result = screen(card(row(
        status="PASS", model_probability=.63,
        ev_per_dollar=-.1, dk_odds=-120)))
    assert result["total_positive_screens"] == 1
    assert result["unverified_model_value_screens"][0]["raw_estimated_ev"] == pytest.approx(.155)


def test_quote_can_expire_during_slow_runner_without_appearing_current():
    too_late = NOW.replace(minute=4)
    out = build_current_value_screens(card(row()), now=too_late)
    assert out["total_positive_screens"] == 0
    assert out["exclusions"]["QUOTE_EXPIRED_BEFORE_FINAL_CARD"] == 1
    assert "No fresh independent positive-EV" in render_phone_card(
        card(row()), now=too_late)


def test_live_finalization_must_not_accept_future_or_naive_clock():
    with pytest.raises(ValueError, match="FINALIZATION_CLOCK_REQUIRED"):
        build_current_value_screens(card(row()), now=datetime(2026, 10, 23))


def test_cfb_screen_without_market_blend_is_excluded():
    result = screen(card(row(sport="CFB", market="TOTAL")))
    assert result["total_positive_screens"] == 0
    assert result["exclusions"]["CFB_BLENDED_EV_UNAVAILABLE"] == 1
