from scripts.validate_nfl_prop_usage_v1_2025 import (
    MAX_CALIBRATION_GAP,
    normal_over_probability,
    scope_metrics,
)


def test_normal_probability_is_half_at_mean():
    assert abs(normal_over_probability(10.0, 2.0, 10.0) - 0.5) < 1e-12


def test_normal_probability_orders_correctly():
    assert normal_over_probability(12.0, 2.0, 10.0) > 0.5
    assert normal_over_probability(8.0, 2.0, 10.0) < 0.5


def test_scope_metrics_uses_preregistered_calibration_definition():
    rows = [
        {"model_p_over": 0.6, "observed_over": 1, "squared_error": 0.16, "baseline_squared_error": 0.25},
        {"model_p_over": 0.4, "observed_over": 0, "squared_error": 0.16, "baseline_squared_error": 0.25},
    ]
    got = scope_metrics(rows)
    assert got["n"] == 2
    assert got["mean_model_p_over"] == 0.5
    assert got["observed_over_rate"] == 0.5
    assert got["calibration_gap"] == 0.0
    assert got["candidate_brier"] == 0.16
    assert got["baseline_brier"] == 0.25
    assert MAX_CALIBRATION_GAP == 0.06
