from __future__ import annotations

import json

import pytest

from sportsedge.sports.cfb.altitude_features import (
    CFBAltitudeFeatureError,
    altitude_delta_ft,
    build_altitude_candidate_features,
    construct_altitude_features,
    parse_altitude_snapshot_jsonl,
)


def _records():
    return [
        {
            "entity_type": "team",
            "id": 1,
            "school": "Away State",
            "location": {
                "id": 11,
                "name": "Away Stadium",
                "elevation_ft": 1000.0,
            },
        },
        {
            "entity_type": "team",
            "id": 2,
            "school": "Listed Home",
            "location": {
                "id": 22,
                "name": "Home Stadium",
                "elevation_ft": 200.0,
            },
        },
        {
            "entity_type": "venue",
            "id": 11,
            "name": "Away Stadium",
            "elevation_ft": 1000.0,
        },
        {
            "entity_type": "venue",
            "id": 22,
            "name": "Home Stadium",
            "elevation_ft": 200.0,
        },
        {
            "entity_type": "venue",
            "id": 99,
            "name": "Neutral Mountain Field",
            "elevation_ft": 5280.0,
        },
    ]


def test_actual_game_venue_drives_neutral_site_delta() -> None:
    rows = _records()
    teams = {r["id"]: r for r in rows if r["entity_type"] == "team"}
    venues = {r["id"]: r for r in rows if r["entity_type"] == "venue"}
    assert altitude_delta_ft(
        teams=teams,
        venues=venues,
        game_venue_id=99,
        away_team_id=1,
    ) == 4280.0


def test_negative_altitude_change_is_clipped_to_zero() -> None:
    rows = _records()
    teams = {r["id"]: r for r in rows if r["entity_type"] == "team"}
    venues = {r["id"]: r for r in rows if r["entity_type"] == "venue"}
    assert altitude_delta_ft(
        teams=teams,
        venues=venues,
        game_venue_id=22,
        away_team_id=1,
    ) == 0.0


def test_linear_candidate_uses_frozen_cap_and_scale() -> None:
    assert build_altitude_candidate_features(
        candidate_id="altitude_linear_capped_v1",
        altitude_delta=6500.0,
    ) == {"altitude_linear_capped_v1": 6.0}


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (999.9, {"altitude_bin_0_1000": 1.0, "altitude_bin_1000_3000": 0.0, "altitude_bin_3000_plus": 0.0}),
        (1000.0, {"altitude_bin_0_1000": 0.0, "altitude_bin_1000_3000": 1.0, "altitude_bin_3000_plus": 0.0}),
        (3000.0, {"altitude_bin_0_1000": 0.0, "altitude_bin_1000_3000": 0.0, "altitude_bin_3000_plus": 1.0}),
    ],
)
def test_bins_match_frozen_cut_points(delta, expected) -> None:
    assert build_altitude_candidate_features(
        candidate_id="altitude_bins_v1",
        altitude_delta=delta,
    ) == expected


def test_short_rest_interaction_requires_rest_evidence() -> None:
    with pytest.raises(CFBAltitudeFeatureError, match="ALTITUDE_AWAY_REST_DAYS_MISSING"):
        build_altitude_candidate_features(
            candidate_id="altitude_short_rest_interaction_v1",
            altitude_delta=4000.0,
        )
    assert build_altitude_candidate_features(
        candidate_id="altitude_short_rest_interaction_v1",
        altitude_delta=4000.0,
        away_rest_days=6,
    ) == {"altitude_short_rest_interaction_v1": 4.0}
    assert build_altitude_candidate_features(
        candidate_id="altitude_short_rest_interaction_v1",
        altitude_delta=4000.0,
        away_rest_days=7,
    ) == {"altitude_short_rest_interaction_v1": 0.0}


def test_missing_game_or_away_home_elevation_fails_closed() -> None:
    rows = _records()
    teams = {r["id"]: r for r in rows if r["entity_type"] == "team"}
    venues = {r["id"]: r for r in rows if r["entity_type"] == "venue"}

    broken_venues = dict(venues)
    broken_venues[99] = {**broken_venues[99], "elevation_ft": None}
    with pytest.raises(CFBAltitudeFeatureError, match="ALTITUDE_GAME_VENUE_ELEVATION_MISSING"):
        altitude_delta_ft(
            teams=teams,
            venues=broken_venues,
            game_venue_id=99,
            away_team_id=1,
        )

    broken_venues = dict(venues)
    broken_venues[11] = {**broken_venues[11], "elevation_ft": None}
    with pytest.raises(CFBAltitudeFeatureError, match="ALTITUDE_AWAY_HOME_VENUE_ELEVATION_MISSING"):
        altitude_delta_ft(
            teams=teams,
            venues=broken_venues,
            game_venue_id=99,
            away_team_id=1,
        )


def test_parser_rejects_duplicate_identity() -> None:
    row = {"entity_type": "venue", "id": 99, "elevation_ft": 5280.0}
    payload = (json.dumps(row) + "\n" + json.dumps(row) + "\n").encode()
    with pytest.raises(CFBAltitudeFeatureError, match="ALTITUDE_ENTITY_DUPLICATE"):
        parse_altitude_snapshot_jsonl(payload)


def test_construction_has_zero_authority_and_no_evaluation() -> None:
    out = construct_altitude_features(
        snapshot_records=_records(),
        game_venue_id=99,
        away_team_id=1,
        candidate_id="altitude_linear_capped_v1",
    )
    assert out["altitude_delta_ft"] == 4280.0
    assert out["features"] == {"altitude_linear_capped_v1": 4.28}
    assert out["fit_performed"] is False
    assert out["evaluation_performed"] is False
    assert out["attempt_consumed"] is False
    assert out["model_p_created"] is False
    assert out["promotion_authority"] is False
    assert out["official_authority"] is False
