"""Sport/market neutral explanations are evidence-only and cannot promote."""
import pytest

from sportsedge.handicap_explanations import handicap_explanation
from sportsedge.phone_display import build_phone_card, render_phone_card
from sportsedge.quote_freshness import QUOTE_FRESH, QUOTE_STALE
from sportsedge.mlb_phone_pitcher_pricing import _pitcher_matchup_factors


@pytest.mark.parametrize("sport,market", [
    ("MLB", "PITCHER_STRIKEOUTS"), ("NBA", "PLAYER_REBOUNDS"),
    ("CFB", "SPREAD"), ("NFL", "PASSING_YARDS"),
    ("NHL", "SAVES"), ("CBB", "TOTAL"),
    ("PGA", "MATCHUP"), ("UFC", "METHOD_OF_VICTORY"),
])
def test_all_sports_markets_report_only_measured_facts(sport, market):
    row = {
        "sport": sport, "market": market, "selection": "UNDER",
        "model_probability": 0.64, "odds_american": -115,
        "quote_freshness": {"code": QUOTE_FRESH},
        "handicap_factors": [
            {"name": "pace", "value": 97.2, "source": "TEST_PROVIDER",
             "direction": "SUPPORTS"},
            {"name": "injury", "value": "questionable", "source": "TEST_REPORT",
             "direction": "OPPOSES"},
        ],
    }
    result = handicap_explanation(row)
    assert result["sport"] == sport
    assert result["market"] == market
    assert len(result["supporting_factors"]) == 1
    assert len(result["opposing_factors"]) == 1
    assert result["research_price_screen"]["research_ev_per_dollar"] > 0
    assert result["research_price_screen"]["research_playable_to_positive_ev"] >= -165
    assert result["verified_play"] is False
    assert all(x["evidence_status"] == "REPORTED_NOT_INDEPENDENTLY_ATTESTED"
               for x in result["evidence"])


def test_nothing_is_invented_when_no_matchup_data_or_price():
    result = handicap_explanation({"sport": "MLB", "market": "PITCHER_STRIKEOUTS",
                                   "side": "UNDER", "model_probability": 0.7})
    assert result["evidence"] == []
    assert result["research_price_screen"] is None
    assert "NO_SOURCE_BACKED_MATCHUP_FACTORS" in result["missing"]
    assert "NO_VALID_BOOK_PRICE" in result["missing"]
    assert "NO_VERIFIED_FRESH_BOOK_QUOTE" in result["missing"]


def test_market_anchored_and_stale_never_pass_as_verified_value():
    row = {"model_probability": 0.8, "odds_american": 120,
           "quote_freshness": {"code": QUOTE_STALE},
           "pricing_provenance": {"lane": "MARKET_ANCHORED"}}
    result = handicap_explanation(row)
    assert result["research_price_screen"] is None
    assert "MARKET_ANCHORED_PROJECTION_CANNOT_PROVE_EDGE" in result["missing"]
    assert "NO_VERIFIED_FRESH_BOOK_QUOTE" in result["missing"]


def test_invalid_provided_factor_does_not_create_angle():
    row = {"handicap_factors": [{"name": "ground balls", "value": 56,
                                  "direction": "SUPPORTS"}]}
    result = handicap_explanation(row)
    assert result["evidence"] == []
    assert "FACTOR_INCOMPLETE" in result["missing"]


def test_card_has_evidence_but_no_promotion():
    row = {"input_index": 0, "sport": "MLB", "market": "PITCHER_STRIKEOUTS",
           "selection": "UNDER", "status": "WATCH_QUOTE_NOT_CURRENT"}
    explanation = handicap_explanation({**row, "handicap_factors": [
        {"name": "strikeout percentage", "value": "15.1%",
         "source": "MLB_STATS", "direction": "SUPPORTS"}]})
    card = {"evaluated_rows": [row], "summary": {"rows": 1},
            "handicap_explanations": [{"input_index": 0, **explanation}]}
    displayed = build_phone_card(card)
    assert displayed["selections"][0]["status"] == "BLOCKED" or displayed["selections"][0]["status"] == "REFRESH REQUIRED"
    text = render_phone_card(card)
    assert "strikeout percentage" in text
    assert "RESEARCH" not in displayed["selections"][0]["status"]


def test_mlb_pitcher_under_strikeout_story_uses_actual_intake_metrics():
    pool = [{"strikeouts": k, "outs": 15, "pitches": 75}
            for k in (2, 3, 2, 4, 3, 3)]
    factors = _pitcher_matchup_factors(
        pool, market="PITCHER_K", side="UNDER", line=3.5)
    assert factors == [{
        "name": "Prior-start strikeouts per start (n=6)",
        "value": 2.83, "source": "MLB StatsAPI pregame prior-start game logs",
        "direction": "SUPPORTS",
    }]
    over = _pitcher_matchup_factors(
        pool, market="PITCHER_K", side="OVER", line=3.5)
    assert over[0]["direction"] == "OPPOSES"
    assert not _pitcher_matchup_factors(
        pool, market="PITCHER_HITS_WALKS_ER", side="UNDER", line=4.5)


def test_mlb_pitcher_ignores_missing_pitch_counts_no_fake_zero():
    pool = [{"strikeouts": 2, "outs": 15} for _ in range(6)]
    assert _pitcher_matchup_factors(
        pool, market="PITCHER_PITCHES", side="UNDER", line=70) == []
