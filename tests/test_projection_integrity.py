from sportsedge.projection_integrity import (
    DEFAULT_SIMULATIONS, ParticipationState, ProjectionComponent,
    build_projection_blend, participation_gate, price_joint_from_simulations,
)


def test_blend_requires_weights_sum_to_one_and_hashes_inputs():
    c = (
        ProjectionComponent("internal", 5.2, .7, "2026-08-22T00:00:00Z", "v1"),
        ProjectionComponent("partner", 5.8, .3, "2026-08-22T00:00:00Z", "v4"),
    )
    a = build_projection_blend(c)
    b = build_projection_blend(c)
    assert abs(a.blended_value - 5.38) < 1e-12
    assert a.blend_hash == b.blend_hash
    assert a.promotion_evidence is False


def test_bad_blend_weights_fail_closed():
    c = (ProjectionComponent("internal", 5.2, .8, "2026-08-22T00:00:00Z", "v1"),)
    try:
        build_projection_blend(c)
    except ValueError as exc:
        assert "sum to 1" in str(exc)
    else:
        raise AssertionError("bad blend weights must fail")


def test_unresolved_participation_is_input_missing():
    passed, reasons = participation_gate(ParticipationState("QUESTIONABLE", "injury_feed", "2026-08-22T00:00:00Z"))
    assert not passed
    assert reasons == ("INPUT_MISSING_PARTICIPATION",)


def test_confirmed_active_participation_passes():
    assert participation_gate(ParticipationState("ACTIVE", "official", "2026-08-22T00:00:00Z")) == (True, ())


def test_joint_price_uses_same_simulation_rows_not_independent_product():
    n = DEFAULT_SIMULATIONS
    # Perfectly correlated 60% legs. Independent product would be 36%, true joint is 60%.
    seq = [True] * int(n * .60) + [False] * (n - int(n * .60))
    result = price_joint_from_simulations({"A": seq, "B": seq}, ("A", "B"))
    assert abs(result.joint_probability - .60) < 1e-12
    assert abs(result.independent_probability - .36) < 1e-12
    assert result.correlation_multiplier > 1.6
    assert result.promotion_evidence is False


def test_joint_price_rejects_mismatched_sim_populations():
    try:
        price_joint_from_simulations({"A": [True] * 50_000, "B": [True] * 49_999}, ("A", "B"))
    except ValueError as exc:
        assert "same simulation population" in str(exc)
    else:
        raise AssertionError("mismatched simulation populations must fail")
