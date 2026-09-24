from __future__ import annotations

from datetime import date

import pytest

from sportsedge.mlb_pregame_feature_adapter import adapt_pregame_bundle
from sportsedge.mlb_umpire_zone_tendency import (
    MLBUmpireZoneTendencyError,
    build_umpire_zone_tendency,
    normalize_game_umpires,
    prepare_called_pitches,
)


def _pitch(*, game_pk: int, game_date: str, strike: bool) -> dict:
    return {
        "game_pk": game_pk,
        "game_date": game_date,
        "description": "called_strike" if strike else "ball",
        "plate_x": 0.0,
        "plate_z": 2.5,
        "sz_top": 3.5,
        "sz_bot": 1.5,
    }


def _balanced_history() -> list[dict]:
    rows: list[dict] = []
    # Same location mix for both umpires: any residual difference is call tendency,
    # not a strike-zone-location composition artifact.
    for i in range(240):
        rows.append(_pitch(game_pk=100, game_date="2026-09-20", strike=i < 144))  # 60%
        rows.append(_pitch(game_pk=200, game_date="2026-09-20", strike=i < 96))   # 40%
    return rows


def test_normalize_game_umpires_accepts_mapping_and_row_forms():
    assert normalize_game_umpires({"100": {"hp_umpire_id": "77"}, 200: 88}) == {100: 77, 200: 88}
    assert normalize_game_umpires([
        {"game_pk": 100, "plate_umpire_id": 77},
        {"gamePk": 200, "umpire_id": 88},
    ]) == {100: 77, 200: 88}


def test_prepare_called_pitches_is_strictly_prior_and_tracks_exclusions():
    rows = _balanced_history()
    rows.extend([
        _pitch(game_pk=100, game_date="2026-09-22", strike=True),
        {**_pitch(game_pk=100, game_date="2026-09-20", strike=True), "description": "swinging_strike"},
        {**_pitch(game_pk=100, game_date="2026-09-20", strike=True), "plate_x": None},
        _pitch(game_pk=300, game_date="2026-09-20", strike=True),
    ])
    selected, counts = prepare_called_pitches(
        rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
    )
    assert len(selected) == 480
    assert all(row["game_date"] < "2026-09-22" for row in selected)
    assert counts["future_or_target_date_excluded"] == 1
    assert counts["non_taken_excluded"] == 1
    assert counts["missing_location_excluded"] == 1
    assert counts["missing_umpire_assignment_excluded"] == 1


def test_location_adjusted_residual_separates_generous_and_tight_umpires():
    rows = _balanced_history()
    generous = build_umpire_zone_tendency(
        pitch_rows=rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
        min_called_pitches=200,
        prior_equivalent_pitches=500,
    )
    tight = build_umpire_zone_tendency(
        pitch_rows=rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=88,
        min_called_pitches=200,
        prior_equivalent_pitches=500,
    )
    assert generous["status"] == "AVAILABLE"
    assert tight["status"] == "AVAILABLE"
    assert generous["observed_called_strike_rate"] == 0.6
    assert tight["observed_called_strike_rate"] == 0.4
    assert generous["expected_called_strike_rate"] == pytest.approx(0.5, abs=1e-5)
    assert tight["expected_called_strike_rate"] == pytest.approx(0.5, abs=1e-5)
    assert generous["called_strike_tendency"] > 0
    assert tight["called_strike_tendency"] < 0
    assert generous["called_strike_tendency"] == pytest.approx(-tight["called_strike_tendency"], abs=1e-6)
    assert generous["model_p_eligible"] is False
    assert generous["promotion_status"] == "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION"


def test_target_day_pitches_cannot_change_prior_tendency():
    baseline = build_umpire_zone_tendency(
        pitch_rows=_balanced_history(),
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
    )
    leaked_rows = _balanced_history() + [
        _pitch(game_pk=100, game_date="2026-09-22", strike=True)
        for _ in range(500)
    ]
    guarded = build_umpire_zone_tendency(
        pitch_rows=leaked_rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
    )
    assert guarded["called_strike_tendency"] == baseline["called_strike_tendency"]
    assert guarded["source_subset_sha256"] == baseline["source_subset_sha256"]
    assert guarded["exclusions"]["future_or_target_date_excluded"] == 500


def test_below_minimum_sample_never_emits_called_strike_tendency():
    result = build_umpire_zone_tendency(
        pitch_rows=_balanced_history(),
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
        min_called_pitches=300,
    )
    assert result["status"] == "BELOW_MIN_CALLED_PITCHES"
    assert result["called_strike_tendency"] is None
    assert result["shrunk_called_strike_bias"] > 0


def test_zone_model_fails_closed_if_only_one_call_class_exists():
    rows = [_pitch(game_pk=100, game_date="2026-09-20", strike=True) for _ in range(250)]
    with pytest.raises(MLBUmpireZoneTendencyError, match="BOTH_BALLS_AND_STRIKES"):
        build_umpire_zone_tendency(
            pitch_rows=rows,
            game_umpires={100: 77},
            target_date=date(2026, 9, 22),
            umpire_id=77,
        )


def test_sample_passing_zone_lane_fills_only_called_strike_adapter_field():
    zone = build_umpire_zone_tendency(
        pitch_rows=_balanced_history(),
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
    )
    bundle = {
        "game_pk": 999005,
        "as_of_utc": "2026-09-22T20:00:00+00:00",
        "umpire": {
            "assignment": {"umpire_id": 77},
            "tendencies": {
                "sample_gate": "PASS",
                "home_plate_games": 20,
                "deltas": {"runs_delta": 0.4, "strikeouts_delta": 1.1, "walks_delta": 0.3},
            },
        },
        "umpire_zone": zone,
    }
    adapted = adapt_pregame_bundle(bundle)
    ump = adapted["family_evaluation"]["umpire_context"]
    assert ump["values"]["called_strike_tendency"] == zone["called_strike_tendency"]
    assert ump["values"]["walk_tendency"] is None
    assert ump["ready"] is False
    assert ump["missing_fields"] == ("walk_tendency",)
    assert adapted["model_p_eligible"] is False
