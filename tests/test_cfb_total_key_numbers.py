from sportsedge.sports.cfb.total_key_numbers import (
    MODEL_P,
    PROMOTION_ELIGIBLE,
    REFERENCE_STATUS,
    TIER_1_CRITICAL,
    TIER_2_HIGH,
    TIER_3_ELEVATED,
    TIER_4_MODERATE,
    crossed_key_totals,
    execution_flags,
    key_total_context,
)


def test_reference_tiers_match_published_ordering():
    assert TIER_1_CRITICAL == (55, 48, 58, 44, 51)
    assert TIER_2_HIGH == (41, 45, 65, 59, 52)
    assert TIER_3_ELEVATED == (62, 69, 37, 47, 49)
    assert TIER_4_MODERATE == (61, 38, 66, 54, 63, 57, 34, 56, 43, 40)


def test_nearest_key_prefers_higher_importance_on_equal_distance():
    context = key_total_context(50.0)
    assert context.nearest_key == 51.0
    assert context.tier == 1
    assert context.tier_name == "CRITICAL"


def test_crossing_51_is_detected_for_51_5_to_50_5():
    crossed = crossed_key_totals(51.5, 50.5)
    assert [(item.nearest_key, item.tier_name) for item in crossed] == [(51.0, "CRITICAL")]


def test_crossing_order_follows_market_move_direction():
    down = crossed_key_totals(60.5, 50.5)
    assert [x.nearest_key for x in down] == [59.0, 58.0, 57.0, 56.0, 55.0, 54.0, 52.0, 51.0]
    up = crossed_key_totals(50.5, 60.5)
    assert [x.nearest_key for x in up] == [51.0, 52.0, 54.0, 55.0, 56.0, 57.0, 58.0, 59.0]


def test_execution_payload_is_context_only_and_has_no_direction_signal():
    payload = execution_flags(51.5, 52.5)
    assert payload["reference_status"] == REFERENCE_STATUS == "EXTERNAL_REFERENCE_ONLY"
    assert payload["model_p"] is MODEL_P is False
    assert payload["promotion_eligible"] is PROMOTION_ELIGIBLE is False
    assert payload["direction_signal"] is None


def test_starting_or_ending_exactly_on_key_is_not_double_counted_as_crossing():
    assert crossed_key_totals(51.0, 50.5) == ()
    assert crossed_key_totals(51.5, 51.0) == ()
