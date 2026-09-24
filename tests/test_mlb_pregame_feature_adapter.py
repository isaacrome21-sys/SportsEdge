from __future__ import annotations

import pytest

from sportsedge.mlb_input_readiness import required_feature_families, scored_input_readiness
from sportsedge.mlb_pregame_feature_adapter import (
    MLBPregameFeatureAdapterError,
    adapt_pregame_bundle,
    attach_pregame_context,
)


def _bundle() -> dict:
    return {
        "game_pk": 999005,
        "as_of_utc": "2026-09-22T20:00:00+00:00",
        "official_date": "2026-09-22",
        "starters": {"probable_pitchers": {"away": {"player_id": 1}, "home": {"player_id": 2}}},
        "lineups": {"confirmed_lineup_ids": {"away": [11, 12], "home": [21, 22]}},
        "statcast": {"status": "AVAILABLE", "matchup": {"bound_pitcher_count": 2}},
        "park_venue": {
            "status": "AVAILABLE",
            "venue": {
                "venue_id": 3313,
                "venue_name": "Example Park",
                "roof_type": "Open",
                "turf_type": "Grass",
                "latitude": 41.95,
                "longitude": -87.65,
                "field_dimensions": {"left_line": 355, "center": 400, "right_line": 353},
            },
        },
        "weather_roof": {
            "status": "AVAILABLE",
            "roof_state": "UNKNOWN",
            "forecast": {
                "temperature": 68,
                "wind_speed": "7 mph",
                "wind_direction": "SW",
                "precip_probability_pct": 15,
            },
        },
        "umpire": {
            "status": "AVAILABLE",
            "assignment": {"umpire_id": 77, "umpire_name": "HP Ump"},
            "tendencies": {
                "sample_gate": "PASS",
                "home_plate_games": 20,
                "deltas": {"runs_delta": 0.4, "strikeouts_delta": 1.1, "walks_delta": 0.3},
            },
        },
        "hybrid_dk": {
            "quotes": [{
                "game_id": "999005",
                "market": "TOTALS",
                "american_odds": -110,
                "sportsbook": "DraftKings",
                "timestamp_source": "INTAKE_STAMPED",
            }]
        },
    }


def test_adapter_never_copies_sportsbook_prices_into_predictive_context():
    adapted = adapt_pregame_bundle(_bundle())
    assert adapted["market_price_data_present"] is True
    assert adapted["excluded_from_predictive_context"] == ["hybrid_dk"]
    assert "hybrid_dk" not in adapted["predictive_context"]
    serialized = repr(adapted["predictive_context"])
    assert "american_odds" not in serialized
    assert "DraftKings" not in serialized
    assert adapted["model_p_eligible"] is False


def test_environment_is_fail_closed_until_fitted_fields_exist():
    adapted = adapt_pregame_bundle(_bundle())
    env = adapted["family_evaluation"]["environment"]
    assert env["ready"] is False
    assert env["values"]["temperature"] == 68.0
    assert env["values"]["wind_speed"] == 7.0
    assert env["values"]["precip_probability"] == 15.0
    assert env["values"]["park_runs_factor"] is None
    assert "park_runs_factor" in env["missing_fields"]
    assert "air_density" in env["missing_fields"]
    assert "roof_state" in env["missing_fields"]


def test_umpire_does_not_alias_game_strikeouts_to_called_strikes():
    adapted = adapt_pregame_bundle(_bundle())
    ump = adapted["family_evaluation"]["umpire_context"]
    assert ump["ready"] is False
    assert ump["values"]["plate_umpire_id"] == 77
    assert ump["values"]["called_strike_tendency"] is None
    assert ump["values"]["walk_tendency"] is None
    assert ump["values"]["run_environment_tendency"] == 0.4
    assert ump["broad_game_context"]["strikeouts_delta"] == 1.1
    assert ump["broad_game_context"]["walks_delta"] == 0.3
    assert "called_strike_tendency" in ump["missing_fields"]


def test_default_attach_is_context_only_and_does_not_change_legacy_readiness_behavior():
    row = {"game_pk": 999005, "market": "TOTALS", "bet_status": "MODEL_CANDIDATE"}
    attached = attach_pregame_context(row, _bundle())
    assert "pregame_context" in attached
    assert "feature_family_readiness" not in attached
    assert scored_input_readiness(attached) == (True, ())


def test_enforced_attach_requires_existing_explicit_readiness_map():
    with pytest.raises(MLBPregameFeatureAdapterError, match="BASE_FEATURE_FAMILY_READINESS_REQUIRED"):
        attach_pregame_context(
            {"game_pk": 999005, "market": "TOTALS"},
            _bundle(),
            enforce_family_readiness=True,
        )


def test_enforced_attach_overwrites_only_owned_families_and_blocks_incomplete_context():
    families = required_feature_families("TOTALS")
    readiness = {name: True for name in families}
    row = {
        "game_pk": 999005,
        "market": "TOTALS",
        "bet_status": "MODEL_CANDIDATE",
        "feature_family_readiness": readiness,
    }
    attached = attach_pregame_context(row, _bundle(), enforce_family_readiness=True)
    assert attached["feature_family_readiness"]["pitcher_quality"] is True
    assert attached["feature_family_readiness"]["environment"] is False
    assert attached["feature_family_readiness"]["umpire_context"] is False
    ready, missing = scored_input_readiness(attached)
    assert ready is False
    assert missing == ("environment", "umpire_context")


def test_game_identity_mismatch_fails_closed():
    with pytest.raises(MLBPregameFeatureAdapterError, match="FEATURE_ROW_GAME_ID_MISMATCH"):
        attach_pregame_context({"game_pk": 123, "market": "TOTALS"}, _bundle())
