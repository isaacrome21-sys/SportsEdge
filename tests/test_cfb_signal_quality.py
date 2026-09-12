import json
from pathlib import Path

import pytest

from scripts.cfb_signal_quality import (
    boosted_break_even,
    evaluate_signal,
    funnel_counts,
    material_line_move,
)


POLICY = json.loads(Path("config/cfb_signal_quality_policy_v1.json").read_text())


def base_row(**overrides):
    row = {
        "market_type": "SPREAD",
        "model_registry_status": "UNFROZEN",
        "promotion_authority": False,
        "model_p": None,
        "truth_gate_pass": False,
        "reference_market_value": -4.5,
        "current_market_value": -5.5,
        "current_odds": -110,
        "odds_age_minutes": 5,
        "handles_required": False,
        "injury_required": True,
        "injury_age_minutes": 30,
        "required_starter_status_unknown": False,
        "outdoor_game": False,
        "underlying_candidate": False,
        "benchmarks": [],
        "sources": [],
    }
    row.update(overrides)
    return row


def test_profit_boost_break_even_is_computed_from_boosted_profit():
    # -110 has 0.90909 profit per unit; a 50% boost makes that 1.363636.
    assert boosted_break_even(-110, 50) == pytest.approx(1 / (1 + (100 / 110) * 1.5))


def test_spread_key_crossing_is_material_even_below_two_points():
    assert material_line_move("SPREAD", -2.5, -3.5)
    assert material_line_move("SPREAD", 7.5, 6.5)


def test_unfrozen_registry_forces_official_zero_even_with_model_p_and_truth_gate_flag():
    result = evaluate_signal(
        base_row(
            model_p=0.61,
            truth_gate_pass=True,
            underlying_candidate=True,
        ),
        POLICY,
    )
    assert result.official_eligible is False
    assert result.lane != "OFFICIAL"
    assert "MODEL_UNFROZEN" in result.reason_codes


def test_frozen_authorized_model_can_surface_official_when_truth_gate_passes():
    result = evaluate_signal(
        base_row(
            model_registry_status="FROZEN",
            promotion_authority=True,
            model_p=0.58,
            truth_gate_pass=True,
        ),
        POLICY,
    )
    assert result.official_eligible is True
    assert result.lane == "OFFICIAL"
    assert result.tier == "CORE"


def test_public_heavy_requires_independent_confirmation():
    result = evaluate_signal(
        base_row(
            tickets_pct=79,
            underlying_candidate=True,
            sources=[{"family": "aggregator_a", "kind": "market", "independent": True}],
        ),
        POLICY,
    )
    assert result.lane == "WATCH"
    assert "PUBLIC_HEAVY_UNCONFIRMED" in result.reason_codes


def test_capper_source_does_not_count_as_independent_confirmation():
    result = evaluate_signal(
        base_row(
            tickets_pct=80,
            underlying_candidate=True,
            sources=[
                {"family": "aggregator_a", "kind": "market", "independent": True},
                {"family": "capper_x", "kind": "capper", "independent": True},
            ],
        ),
        POLICY,
    )
    assert "PUBLIC_HEAVY_UNCONFIRMED" in result.reason_codes


def test_two_independent_market_source_families_clear_public_confirmation_gate():
    result = evaluate_signal(
        base_row(
            tickets_pct=80,
            underlying_candidate=True,
            sources=[
                {"family": "aggregator_a", "kind": "market", "independent": True},
                {"family": "sportsbook_native", "kind": "market", "independent": True},
            ],
        ),
        POLICY,
    )
    assert "PUBLIC_HEAVY_UNCONFIRMED" not in result.reason_codes
    assert result.lane == "HYBRID_CONTEXT"


def test_stale_injury_input_downgrades_to_watch():
    result = evaluate_signal(
        base_row(injury_age_minutes=999, underlying_candidate=True),
        POLICY,
    )
    assert result.lane == "WATCH"
    assert "INJURY_STALE_OR_UNKNOWN" in result.reason_codes


def test_missing_outdoor_weather_downgrades_to_watch():
    result = evaluate_signal(
        base_row(
            outdoor_game=True,
            weather_available=False,
            weather_age_minutes=None,
            underlying_candidate=True,
        ),
        POLICY,
    )
    assert result.lane == "WATCH"
    assert "WEATHER_STALE_OR_MISSING" in result.reason_codes


def test_benchmark_disagreement_is_diagnostic_watch_not_model_p():
    result = evaluate_signal(
        base_row(
            underlying_candidate=True,
            benchmarks=[
                {"name": "SP+", "value": -2.0},
                {"name": "FPI", "value": -6.0},
            ],
        ),
        POLICY,
    )
    assert result.lane == "WATCH"
    assert result.model_authorized is False
    assert "BENCHMARK_DISAGREEMENT" in result.reason_codes


def test_price_decay_when_half_of_reference_edge_is_gone():
    result = evaluate_signal(
        base_row(
            underlying_candidate=True,
            reference_edge=0.08,
            current_edge=0.035,
        ),
        POLICY,
    )
    assert result.lane == "WATCH"
    assert "PRICE_DECAY" in result.reason_codes


def test_promo_overlay_remains_promo_value_without_model_authority():
    result = evaluate_signal(
        base_row(
            underlying_candidate=True,
            promo={"boost_pct": 50},
        ),
        POLICY,
    )
    assert result.lane == "PROMO_VALUE"
    assert result.official_eligible is False
    assert result.boosted_break_even == pytest.approx(boosted_break_even(-110, 50))
    assert "PROMO_ONLY_EDGE" in result.reason_codes


def test_funnel_never_invents_official_rows():
    rows = [
        evaluate_signal(base_row(underlying_candidate=True), POLICY),
        evaluate_signal(base_row(underlying_candidate=True, promo={"boost_pct": 50}), POLICY),
        evaluate_signal(base_row(injury_age_minutes=999, underlying_candidate=True), POLICY),
    ]
    counts = funnel_counts(rows)
    assert counts["scanned"] == 3
    assert counts["official"] == 0
    assert counts["model_candidates"] == 0
