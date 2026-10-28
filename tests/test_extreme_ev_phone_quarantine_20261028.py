"""Owner +40% EV quarantine: no headline/LEAN/value-screen promotion.

Synthetic rows test only the presentation boundary. They do not assert
authenticated DK prices, calibrated model probabilities or betting authority.
"""
from datetime import datetime, timezone

import pytest

from sportsedge.phone_display import (
    EXTREME_CLAIMED_EV_QUARANTINE,
    build_phone_card,
    build_current_value_screens,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
TIP = "2026-10-28T13:00:00+00:00"


def _card(*, probability=0.95, reported_ev=2.818,
          price=300, sport="NBA", blend=None, fresh=True):
    row = {
        "sport": sport, "market": "MONEYLINE", "selection": "HOME",
        "status": "RESEARCH_CANDIDATE_NOT_VALIDATED",
        "estimate_p": probability, "ev_per_dollar": reported_ev,
        "odds_american": price, "kickoff_utc": TIP,
        "pricing_provenance": {"lane": "INDEPENDENT"},
        "quote_freshness": (
            {"code": "QUOTE_FRESH_UNDER_180S", "age_seconds": 30}
            if fresh else {"code": "QUOTE_STALE_OVER_180S", "age_seconds": 400}
        ),
    }
    if blend is not None:
        row["pricing_lanes"] = {
            "lane_b_anchored": {
                "status": "PRICED", "estimate_p": blend[0],
                "ev_per_dollar": blend[1],
                "fair_american": -110, "anchor": {"weight": 0.85},
            },
        }
    return {
        "as_of_utc": NOW.isoformat(),
        "min_ev": 0.02,
        "summary": {"rows": 1},
        "evaluated_rows": [row],
        "selection_intake": [{
            "sport": sport, "away": "Away", "home": "Home",
            "market": "MONEYLINE", "side": "HOME", "kickoff": TIP,
        }],
    }


@pytest.mark.parametrize("reported_ev", [0.40, 0.40001, 2.818])
def test_at_or_above_existing_owner_quarantine_is_not_lean(reported_ev):
    card = _card(probability=0.7, reported_ev=reported_ev, price=100)
    view = build_phone_card(card)
    selection = view["selections"][0]
    assert EXTREME_CLAIMED_EV_QUARANTINE == 0.40
    assert selection["status"] == "QUARANTINED"
    assert selection["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"
    assert selection["estimated_ev"] is None
    assert selection["probability"] is None
    assert card["evaluated_rows"][0]["ev_per_dollar"] == reported_ev


def test_raw_extreme_cfb_stays_quarantined_despite_low_market_blend():
    card = _card(sport="CFB", probability=0.9, reported_ev=1.8,
                 price=100, blend=(0.52, 0.04))
    view = build_phone_card(card)
    assert view["selections"][0]["status"] == "QUARANTINED"
    screens = build_current_value_screens(card, now=NOW)
    assert screens["unverified_model_value_screens"] == []
    assert screens["exclusions"]["EXTREME_CLAIMED_EV_QUARANTINE"] == 1


def test_repriced_extreme_is_suppressed_even_if_stored_ev_small():
    card = _card(probability=0.8, reported_ev=0.05, price=100)
    assert build_phone_card(card)["selections"][0]["status"] == "LEAN"
    # Repriced EV at +100 is 60%, so current-value screen must refuse.
    screens = build_current_value_screens(card, now=NOW)
    assert screens["unverified_model_value_screens"] == []
    assert screens["exclusions"]["EXTREME_CLAIMED_EV_QUARANTINE"] == 1


def test_extreme_blended_claim_quarantined_even_if_raw_ev_small():
    card = _card(sport="NFL", probability=0.52, reported_ev=0.04,
                 price=100, blend=(0.9, 0.8))
    assert build_phone_card(card)["selections"][0]["status"] == "QUARANTINED"


def test_stale_extreme_cannot_reenter_stale_ranked_selection():
    card = _card(fresh=False)
    selection = build_phone_card(card)["selections"][0]
    assert selection["status"] == "QUARANTINED"
    assert selection["estimated_ev"] is None


def test_below_quarantine_threshold_keeps_research_only_lean():
    card = _card(probability=0.6995, reported_ev=0.399, price=100)
    selection = build_phone_card(card)["selections"][0]
    assert selection["status"] == "LEAN"
    assert selection["estimated_ev"] == pytest.approx(0.399)


@pytest.mark.parametrize("hidden", [
    {"raw_ev_per_dollar": 2.818},
    {"reported_ev_per_dollar": 0.40},
    {"pricing_lanes": {"lane_a_independent": {
        "ev_per_dollar": 0.04, "reported_ev_per_dollar": 0.41}}},
    {"independent_projection": {
        "estimate_p": 0.52, "ev_per_dollar": 0.04,
        "raw_ev_per_dollar": 2.818,
        "paired_market_status": "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"}},
])
def test_hidden_raw_or_reported_ev_alias_cannot_bypass_phone_quarantine(hidden):
    # Synthetic adversarial input; no claim of real DK source provenance.
    card = _card(probability=0.52, reported_ev=0.04, price=100)
    card["evaluated_rows"][0].update(hidden)
    assert build_phone_card(card)["selections"][0]["status"] == "QUARANTINED"
    assert card["evaluated_rows"][0]["ev_per_dollar"] == 0.04
    screens = build_current_value_screens(card, now=NOW)
    assert screens["unverified_model_value_screens"] == []
    assert screens["exclusions"]["EXTREME_CLAIMED_EV_QUARANTINE"] == 1


@pytest.mark.parametrize("malformed", [
    {"raw_ev_per_dollar": "nan"},
    {"reported_ev_per_dollar": float("inf")},
    {"pricing_lanes": {"lane_b_anchored": {"ev_per_dollar": True}}},
    {"independent_projection": {
        "estimate_p": 0.52, "ev_per_dollar": 0.04,
        "reported_ev_per_dollar": "281.8%",
        "paired_market_status": "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"}},
])
def test_malformed_ev_claim_fails_closed_without_fake_extreme_label(malformed):
    card = _card(probability=0.52, reported_ev=0.04, price=100)
    card["evaluated_rows"][0].update(malformed)
    selection = build_phone_card(card)["selections"][0]
    assert selection["status"] == "QUARANTINED"
    assert selection["reason"] == "PROP_EV_CLAIM_INVALID"
    assert selection["estimated_ev"] is None
    screens = build_current_value_screens(card, now=NOW)
    assert screens["unverified_model_value_screens"] == []
    assert screens["exclusions"]["PROP_EV_CLAIM_INVALID"] == 1


@pytest.mark.parametrize("hidden", [
    {"pricing_lanes": {"lane_b_anchored": {
        "estimate_p": 1.5, "ev_per_dollar": 0.04}}},
    {"pricing_lanes": {"lane_a_independent": {
        "model_probability": -0.01, "ev_per_dollar": 0.04}}},
    {"pricing_lanes": {"lane_b_anchored": {
        "estimate_p": float("nan"), "ev_per_dollar": 0.04}}},
    {"pricing_lanes": {"lane_b_anchored": {
        "estimate_p": True, "ev_per_dollar": 0.04}}},
    {"independent_projection": {
        "estimate_p": float("inf"), "ev_per_dollar": 0.04,
        "paired_market_status": "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"}},
])
def test_impossible_hidden_probability_never_becomes_value_screen(hidden):
    # An invalid Lane B p must not be displayed as 150% probability or
    # silently fall back to a small blended EV while preserving LEAN.
    card = _card(sport="CFB", probability=0.52, reported_ev=0.04,
                 price=100, blend=(0.52, 0.04))
    card["evaluated_rows"][0].update(hidden)
    selection = build_phone_card(card)["selections"][0]
    assert selection["status"] == "QUARANTINED"
    assert selection["reason"] == "PROP_PROBABILITY_CLAIM_INVALID"
    assert selection["blended"] is None
    assert selection["estimated_ev"] is None
    screens = build_current_value_screens(card, now=NOW)
    assert screens["unverified_model_value_screens"] == []
    assert screens["exclusions"]["PROP_PROBABILITY_CLAIM_INVALID"] == 1
    assert card["evaluated_rows"][0]["ev_per_dollar"] == 0.04
