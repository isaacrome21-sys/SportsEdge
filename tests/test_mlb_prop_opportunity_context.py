from sportsedge.mlb_prop_opportunity_context import (
    MLBPropOpportunityObservation,
    MODEL_P_ELIGIBLE,
    TRUTH_GATE_ELIGIBLE,
    prop_evaluation_sequence,
)


def _base(**overrides):
    data = {
        "game_id": "2026-08-31-NYM-TB",
        "entity_id": "pitcher-123",
        "prop_family": "pitcher_strikeouts",
        "as_of_utc": "2026-08-31T16:00:00Z",
        "source_uri": "https://example.com/objective-source",
        "source_sha256": "a" * 64,
        "features": {"pitcher_k_rate": 0.28, "swstr_rate": 0.14},
    }
    data.update(overrides)
    return data


def test_context_is_ineligible_at_birth():
    obs = MLBPropOpportunityObservation(**_base())
    assert obs.model_p_eligible is False
    assert obs.truth_gate_eligible is False
    assert MODEL_P_ELIGIBLE is False
    assert TRUTH_GATE_ELIGIBLE is False


def test_social_and_market_fields_are_rejected():
    for bad_key in ("social_pick", "ticket_pct", "sportsbook_price", "market_probability", "closing_line"):
        try:
            MLBPropOpportunityObservation(**_base(features={bad_key: 1}))
        except ValueError as exc:
            assert "contamination prohibited" in str(exc)
        else:
            raise AssertionError(f"expected {bad_key} to be rejected")


def test_unknown_feature_is_rejected():
    try:
        MLBPropOpportunityObservation(**_base(features={"mystery_metric": 1.0}))
    except ValueError as exc:
        assert "unknown/unapproved features" in str(exc)
    else:
        raise AssertionError("unknown feature should fail closed")


def test_prop_family_contracts_cover_requested_markets():
    families = {
        "pitcher_strikeouts": {"platoon": "R", "whiff_by_pitch": {"FF": 0.31}},
        "batter_hits": {"lineup_slot": 2, "hard_hit_rate": 0.44},
        "total_bases": {"iso": 0.240, "weather_carry": 1.06},
        "home_runs": {"barrel_rate": 0.15, "park_hr_factor": 1.22},
        "stolen_bases": {"sprint_speed": 29.4, "attempt_rate": 0.18},
    }
    for family, features in families.items():
        obs = MLBPropOpportunityObservation(**_base(prop_family=family, features=features))
        assert obs.prop_family == family


def test_run_it_sequence_keeps_price_downstream():
    assert prop_evaluation_sequence() == (
        "confirm_lineup_and_starter",
        "platoon_and_matchup",
        "park_weather_environment",
        "quality_of_contact_or_pitch_skill",
        "distribution",
        "market_price",
        "ev",
        "execution_gate",
    )
