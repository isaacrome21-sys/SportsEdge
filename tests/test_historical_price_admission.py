import pytest

from sportsedge.research.historical_price_admission import (
    assert_no_market_contamination,
    validate_historical_snapshot,
)


def base_snapshot(market_key="h2h"):
    outcomes = [
        {"name": "Away", "price": -110},
        {"name": "Home", "price": -110},
    ]
    if market_key == "spreads":
        outcomes = [
            {"name": "Away", "price": -110, "point": 3.5},
            {"name": "Home", "price": -110, "point": -3.5},
        ]
    if market_key == "totals":
        outcomes = [
            {"name": "Over", "price": -110, "point": 47.5},
            {"name": "Under", "price": -110, "point": 47.5},
        ]
    return {
        "sport_key": "americanfootball_nfl",
        "event_id": "event-1",
        "commence_time_utc": "2020-10-19T00:15:00Z",
        "snapshot_timestamp_utc": "2020-10-18T12:00:00Z",
        "book_key": "draftkings",
        "book_title": "DraftKings",
        "book_last_update_utc": "2020-10-18T11:58:00Z",
        "market_key": market_key,
        "outcomes": outcomes,
        "raw_byte_sha256": "a" * 64,
        "retrieved_at_utc": "2026-09-13T13:00:00Z",
        "source_request_sha256": "b" * 64,
    }


def test_moneyline_pair_is_admitted_but_has_zero_authority():
    out = validate_historical_snapshot(base_snapshot())
    assert out["admitted"] is True
    assert out["market_family"] == "moneyline"
    assert out["role"] == "REPLAY_BENCHMARK_ONLY"
    assert out["sportsbook_inputs_allowed_in_model_fit"] is False
    assert out["model_p_authority"] is False
    assert out["promotion_authority"] is False
    assert out["official_authority"] is False


def test_spread_requires_matched_opposite_points():
    bad = base_snapshot("spreads")
    bad["outcomes"][1]["point"] = -3.0
    with pytest.raises(ValueError, match="matched opposite points"):
        validate_historical_snapshot(bad)


def test_total_requires_over_under_and_same_number():
    good = validate_historical_snapshot(base_snapshot("totals"))
    assert good["market_family"] == "game_total"
    bad = base_snapshot("totals")
    bad["outcomes"][1]["point"] = 48.0
    with pytest.raises(ValueError, match="same total"):
        validate_historical_snapshot(bad)


def test_post_kickoff_snapshot_blocks():
    bad = base_snapshot()
    bad["snapshot_timestamp_utc"] = bad["commence_time_utc"]
    with pytest.raises(ValueError, match="at/after commence"):
        validate_historical_snapshot(bad)


def test_book_update_after_snapshot_blocks():
    bad = base_snapshot()
    bad["book_last_update_utc"] = "2020-10-18T12:01:00Z"
    with pytest.raises(ValueError, match="cannot exceed"):
        validate_historical_snapshot(bad)


def test_bad_hash_blocks():
    bad = base_snapshot()
    bad["raw_byte_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="raw_byte_sha256 must be SHA256"):
        validate_historical_snapshot(bad)


def test_market_contamination_firewall_blocks_price_features():
    assert_no_market_contamination(["offense_epa", "defense_success_rate", "weather_wind"])
    with pytest.raises(ValueError, match="market contamination"):
        assert_no_market_contamination(["offense_epa", "closing_spread"])
