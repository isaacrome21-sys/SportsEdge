from sportsedge.ufc_engine import (
    FighterSnapshot, FightContext, project_fight, monte_carlo,
    no_vig_two_way, expected_value, truth_gate,
)


def fighter(name: str, elo: float, recent: float, missing: float = 0.0):
    return FighterSnapshot(
        name=name, age=30, height_in=72, reach_in=74, stance="Orthodox",
        wins=15, losses=3, sig_strikes_landed_pm=4.0,
        sig_strikes_absorbed_pm=3.0, sig_strike_accuracy=0.50,
        sig_strike_defense=0.55, takedowns_per_15=2.0,
        takedown_accuracy=0.45, takedown_defense=0.70,
        submissions_per_15=0.5, control_seconds_per_15=150,
        knockdowns_per_15=0.2, finish_win_rate=0.55,
        finish_loss_rate=0.20, recent_win_rate=recent,
        strength_of_schedule=0.60, elo=elo, missingness=missing,
    )


def test_projection_sums():
    p = project_fight(fighter("A", 1600, .7), fighter("B", 1500, .5), FightContext())
    assert abs(p.p_a_win + p.p_b_win - 1.0) < 1e-9
    assert abs(p.p_goes_distance + p.p_inside_distance - 1.0) < 1e-9


def test_monte_carlo_reproducible():
    p = project_fight(fighter("A", 1600, .7), fighter("B", 1500, .5), FightContext())
    a = monte_carlo(p, n=5000, seed=7)
    b = monte_carlo(p, n=5000, seed=7)
    assert a == b


def test_no_vig_and_ev():
    a, b = no_vig_two_way(-150, +130)
    assert abs(a + b - 1.0) < 1e-9
    assert expected_value(0.60, -150) == 0.0


def test_truth_gate_uncertainty_blocks():
    a, _ = no_vig_two_way(-110, -110)
    out = truth_gate(prob=.58, odds=-110, market_novig=a, uncertainty=.25)
    assert out["pass"] is False
