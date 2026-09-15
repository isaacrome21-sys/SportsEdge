from datetime import datetime, timezone

import pytest

from scripts.build_cfb_signal_input import build_rows


REGISTRY = {"status": "UNFROZEN", "promotion_authority": False}


def capture_bundle():
    return {
        "as_of": "2026-09-12T14:10:00Z",
        "markets": [
            {
                "game_id": "ou-mich",
                "market_id": "ou-mich-spread-ou",
                "market_type": "SPREAD",
                "selection": "Oklahoma",
                "sportsbook": "FanDuel",
                "current_odds": -114,
                "current_market_value": -4.5,
                "reference_market_value": -2.5,
                "captured_at": "2026-09-12T14:06:29Z",
                "underlying_candidate": True,
                "sources": [{"family": "fanduel", "kind": "sportsbook", "independent": True}],
            }
        ],
        "games": [
            {
                "game_id": "ou-mich",
                "public": {
                    "tickets_pct": 72,
                    "money_pct": 68,
                    "required": True,
                    "captured_at": "2026-09-12T14:05:00Z",
                    "sources": [{"family": "covers", "kind": "market", "independent": True}],
                },
                "injury": {
                    "required": True,
                    "captured_at": "2026-09-12T13:30:00Z",
                    "required_starter_status_unknown": False,
                    "sources": [{"family": "team-report", "kind": "news", "independent": True}],
                },
                "weather": {
                    "outdoor_game": True,
                    "available": True,
                    "severe_weather": True,
                    "captured_at": "2026-09-12T13:45:00Z",
                    "sources": [{"family": "weather", "kind": "weather", "independent": True}],
                },
                "benchmarks": [{"name": "SP+", "value": -6.0}],
            }
        ],
    }


def test_adapter_computes_freshness_and_binds_fail_closed_registry():
    row = build_rows(capture_bundle(), REGISTRY)[0]
    assert row["model_registry_status"] == "UNFROZEN"
    assert row["promotion_authority"] is False
    assert row["model_p"] is None
    assert row["truth_gate_pass"] is False
    assert row["odds_age_minutes"] == pytest.approx(3.516667, abs=1e-6)
    assert row["handles_age_minutes"] == pytest.approx(5.0)
    assert row["injury_age_minutes"] == pytest.approx(40.0)
    assert row["weather_age_minutes"] == pytest.approx(25.0)
    assert row["severe_weather"] is True
    assert row["tickets_pct"] == 72
    assert {source["family"] for source in row["sources"]} == {"fanduel", "covers", "team-report", "weather"}


def test_adapter_never_accepts_arbitrary_model_p_while_registry_unfrozen():
    capture = capture_bundle()
    capture["markets"][0]["model_p"] = 0.99
    capture["markets"][0]["truth_gate_pass"] = True
    row = build_rows(capture, REGISTRY)[0]
    assert row["model_p"] is None
    assert row["truth_gate_pass"] is False


def test_adapter_rejects_future_capture_timestamp():
    capture = capture_bundle()
    capture["markets"][0]["captured_at"] = "2026-09-12T14:11:00Z"
    with pytest.raises(ValueError, match="after as_of"):
        build_rows(capture, REGISTRY)


def test_adapter_rejects_naive_as_of_override():
    with pytest.raises(ValueError, match="timezone"):
        build_rows(capture_bundle(), REGISTRY, as_of=datetime(2026, 9, 12, 14, 10))


def test_adapter_allows_authorized_model_p_only_when_registry_is_frozen():
    capture = capture_bundle()
    capture["markets"][0]["model_p"] = 0.58
    capture["markets"][0]["truth_gate_pass"] = True
    registry = {"status": "FROZEN", "promotion_authority": True}
    row = build_rows(capture, registry, as_of=datetime(2026, 9, 12, 14, 10, tzinfo=timezone.utc))[0]
    assert row["model_p"] == 0.58
    assert row["truth_gate_pass"] is True
