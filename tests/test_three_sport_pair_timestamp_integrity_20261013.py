"""Adversarial DK pair-evidence regressions for MLB/NFL/CFB prop research.

Quote timestamps originate in two independently supplied rows; odds,
models, and clocks are synthetic. No network or paid archival collectors.
"""
import pytest

from sportsedge.research_three_sport_bridge import price_three_sport_research


NOW = "2026-10-11T20:30:00Z"
KICKOFF = "2026-10-12T03:00:00Z"


def model(sport):
    return {
        "sport": sport, "game_id": "fixture-42", "market": "PLAYER_RECEIVING_YARDS",
        "player_id": "athlete-1", "line": 49.5, "selection": "OVER",
        "estimate_p": 0.55, "push_p": 0.0,
        "status": "PRICED_RESEARCH", "model_source": "SYNTHETIC_MODEL",
        "market_blind": True, "as_of_utc": "2026-10-11T20:29:00Z",
        "kickoff_utc": KICKOFF,
        "home_team": "Boise State Broncos" if sport == "CFB" else "Home",
        "away_team": "Wyoming Cowboys" if sport == "CFB" else "Away",
    }


def quote(sport, side, stamp, **extras):
    row = {
        "sport": sport, "game_id": "fixture-42", "market": "PLAYER_RECEIVING_YARDS",
        "player_id": "athlete-1", "line": 49.5, "selection": side,
        "odds": -110, "book": "draftkings", "quote_captured_at": stamp,
        "home_team": "Boise State Broncos" if sport == "CFB" else "Home",
        "away_team": "Wyoming Cowboys" if sport == "CFB" else "Away",
    }
    row.update(extras)
    return row


def price(sport, own, counterpart):
    return price_three_sport_research(
        [model(sport)], [own, counterpart], as_of=NOW)["rows"][0]


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_two_sided_quotes_with_120_seconds_skew_are_accepted(sport):
    # Both are fresh as of NOW; exactly 120 sec apart must pass.
    row = price(sport,
                quote(sport, "OVER", "2026-10-11T20:29:50Z"),
                quote(sport, "UNDER", "2026-10-11T20:27:50Z"))
    assert row["status"] == "RESEARCH_CANDIDATE_NOT_VALIDATED"
    assert row["paired_quote_skew_seconds"] == 120.0
    assert len(row["paired_quote_captured_at"]) == 2
    assert "dk_no_vig_p" in row


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_121_second_skew_cannot_supply_market_benchmark(sport):
    row = price(sport,
                quote(sport, "OVER", "2026-10-11T20:29:50Z"),
                quote(sport, "UNDER", "2026-10-11T20:27:49Z"))
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "PAIRED_QUOTES_CAPTURE_WINDOW_EXCEEDED"
    assert "dk_no_vig_p" not in row


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
@pytest.mark.parametrize("missing_side", ["OVER", "UNDER"])
def test_missing_capture_on_either_side_refuses_two_sided_benchmark(sport, missing_side):
    own = quote(sport, "OVER",
                None if missing_side == "OVER" else "2026-10-11T20:29:40Z")
    other = quote(sport, "UNDER",
                  None if missing_side == "UNDER" else "2026-10-11T20:29:40Z")
    row = price(sport, own, other)
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "PAIRED_QUOTES_CAPTURE_TIMESTAMPS_REQUIRED"
    assert "dk_no_vig_p" not in row


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_opposite_side_stale_blocks_actionability_even_when_our_side_is_fresh(sport):
    row = price(sport,
                quote(sport, "OVER", "2026-10-11T20:27:55Z"),
                quote(sport, "UNDER", "2026-10-11T20:26:10Z"))
    assert row["paired_quote_skew_seconds"] == 105.0
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_status"] == "RESEARCH_AGED_QUOTE_150_TO_300S"
    assert row["research_only"] is True
    assert row["staking_authority"] is False


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_future_timestamp_on_opposite_side_is_never_fresh(sport):
    row = price(sport,
                quote(sport, "OVER", "2026-10-11T20:29:40Z"),
                quote(sport, "UNDER", "2026-10-11T20:30:01Z"))
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_status"] == "STALE_QUOTE"


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_unparseable_counterpart_timestamp_is_not_an_evidenced_pair(sport):
    row = price(sport,
                quote(sport, "OVER", "2026-10-11T20:29:40Z"),
                quote(sport, "UNDER", "not-a-time"))
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert "dk_no_vig_p" not in row
