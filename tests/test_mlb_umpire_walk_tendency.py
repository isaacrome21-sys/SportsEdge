from __future__ import annotations

from datetime import date

import pytest

from sportsedge.mlb_pregame_feature_adapter import adapt_pregame_bundle
from sportsedge.mlb_umpire_walk_tendency import (
    MLBUmpireWalkTendencyError,
    build_umpire_walk_tendency,
    expected_walk_probabilities,
    prepare_plate_appearances,
)


def _pa(
    *,
    game_pk: int,
    game_date: str,
    walk: bool,
    batter: int = 10,
    pitcher: int = 20,
    event: str | None = None,
) -> dict:
    return {
        "game_pk": game_pk,
        "game_date": game_date,
        "events": event if event is not None else ("walk" if walk else "field_out"),
        "batter": batter,
        "pitcher": pitcher,
    }


def _balanced_history() -> list[dict]:
    rows: list[dict] = []
    # Identical batter/pitcher composition; only observed BB rate differs by umpire.
    for i in range(600):
        rows.append(_pa(game_pk=100, game_date="2026-09-20", walk=i < 90))   # 15%
        rows.append(_pa(game_pk=200, game_date="2026-09-20", walk=i < 30))   # 5%
    return rows


def test_prepare_plate_appearances_is_strictly_prior_and_excludes_intentional_walks():
    rows = _balanced_history()
    rows.extend([
        _pa(game_pk=100, game_date="2026-09-22", walk=True),
        _pa(game_pk=100, game_date="2026-09-20", walk=True, event="intent_walk"),
        {"game_pk": 100, "game_date": "2026-09-20", "events": ""},
        _pa(game_pk=300, game_date="2026-09-20", walk=True),
        {**_pa(game_pk=100, game_date="2026-09-20", walk=True), "batter": None},
    ])
    selected, counts = prepare_plate_appearances(
        rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
    )
    assert len(selected) == 1200
    assert all(row["game_date"] < "2026-09-22" for row in selected)
    assert counts["future_or_target_date_excluded"] == 1
    assert counts["intentional_walk_excluded"] == 1
    assert counts["non_terminal_excluded"] == 1
    assert counts["missing_umpire_assignment_excluded"] == 1
    assert counts["missing_batter_or_pitcher_excluded"] == 1


def test_expected_walk_probability_adjusts_for_batter_propensity():
    rows: list[dict] = []
    # Same pitcher, two batters with very different prior BB propensities.
    for i in range(300):
        rows.append({"walk": 1 if i < 60 else 0, "batter": 1, "pitcher": 9})
        rows.append({"walk": 1 if i < 15 else 0, "batter": 2, "pitcher": 9})
    expected = expected_walk_probabilities(rows, batter_prior_pa=40, pitcher_prior_pa=200)
    high_batter_mean = sum(expected[0::2]) / 300
    low_batter_mean = sum(expected[1::2]) / 300
    assert high_batter_mean > low_batter_mean
    assert 0 < low_batter_mean < 1
    assert 0 < high_batter_mean < 1


def test_adjusted_residual_separates_walk_generous_and_tight_umpires():
    rows = _balanced_history()
    generous = build_umpire_walk_tendency(
        pitch_rows=rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
        min_plate_appearances=500,
        prior_equivalent_pa=1000,
    )
    tight = build_umpire_walk_tendency(
        pitch_rows=rows,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=88,
        min_plate_appearances=500,
        prior_equivalent_pa=1000,
    )
    assert generous["status"] == "AVAILABLE"
    assert tight["status"] == "AVAILABLE"
    assert generous["observed_walk_rate"] == 0.15
    assert tight["observed_walk_rate"] == 0.05
    assert generous["walk_tendency"] > 0
    assert tight["walk_tendency"] < 0
    assert generous["model_p_eligible"] is False
    assert generous["promotion_status"] == "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION"


def test_target_day_plate_appearances_cannot_change_prior_tendency_or_hash():
    baseline = build_umpire_walk_tendency(
        pitch_rows=_balanced_history(),
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
    )
    leaked = _balanced_history() + [
        _pa(game_pk=100, game_date="2026-09-22", walk=True)
        for _ in range(800)
    ]
    guarded = build_umpire_walk_tendency(
        pitch_rows=leaked,
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
    )
    assert guarded["walk_tendency"] == baseline["walk_tendency"]
    assert guarded["source_subset_sha256"] == baseline["source_subset_sha256"]
    assert guarded["exclusions"]["future_or_target_date_excluded"] == 800


def test_below_minimum_sample_does_not_emit_walk_tendency():
    result = build_umpire_walk_tendency(
        pitch_rows=_balanced_history(),
        game_umpires={100: 77, 200: 88},
        target_date=date(2026, 9, 22),
        umpire_id=77,
        min_plate_appearances=700,
    )
    assert result["status"] == "BELOW_MIN_PLATE_APPEARANCES"
    assert result["walk_tendency"] is None
    assert result["shrunk_walk_bias"] > 0


def test_walk_model_fails_closed_when_history_has_only_one_outcome_class():
    rows = [_pa(game_pk=100, game_date="2026-09-20", walk=False) for _ in range(600)]
    with pytest.raises(MLBUmpireWalkTendencyError, match="WALKS_AND_NON_WALKS"):
        build_umpire_walk_tendency(
            pitch_rows=rows,
            game_umpires={100: 77},
            target_date=date(2026, 9, 22),
            umpire_id=77,
        )


def _complete_umpire_bundle(*, validated: bool) -> dict:
    validation = {
        "called_strike_tendency": True,
        "walk_tendency": True,
        "run_environment_tendency": True,
    } if validated else {}
    return {
        "game_pk": 999005,
        "umpire": {
            "assignment": {"umpire_id": 77},
            "tendencies": {
                "sample_gate": "PASS",
                "home_plate_games": 20,
                "deltas": {"runs_delta": 0.4, "strikeouts_delta": 1.1, "walks_delta": 0.3},
            },
        },
        "umpire_zone": {
            "status": "AVAILABLE",
            "model_version": "zone_logit_residual_v1",
            "called_strike_tendency": 0.012,
            "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        },
        "umpire_walk": {
            "status": "AVAILABLE",
            "model_version": "batter_pitcher_eb_walk_residual_v1",
            "walk_tendency": 0.006,
            "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        },
        "umpire_feature_validation": validation,
    }


def test_available_umpire_research_values_do_not_auto_promote_readiness():
    adapted = adapt_pregame_bundle(_complete_umpire_bundle(validated=False))
    ump = adapted["family_evaluation"]["umpire_context"]
    assert ump["input_complete"] is True
    assert ump["missing_fields"] == ()
    assert ump["values"]["called_strike_tendency"] == 0.012
    assert ump["values"]["walk_tendency"] == 0.006
    assert ump["ready"] is False
    assert ump["validation_blockers"] == (
        "called_strike_tendency",
        "walk_tendency",
        "run_environment_tendency",
    )
    assert adapted["feature_family_readiness"]["umpire_context"] is False


def test_explicit_validation_flags_are_required_for_umpire_readiness():
    adapted = adapt_pregame_bundle(_complete_umpire_bundle(validated=True))
    ump = adapted["family_evaluation"]["umpire_context"]
    assert ump["input_complete"] is True
    assert ump["validation_blockers"] == ()
    assert ump["ready"] is True
    assert adapted["feature_family_readiness"]["umpire_context"] is True
    # The acquisition adapter itself remains context-only; this does not create Model_P.
    assert adapted["model_p_eligible"] is False
