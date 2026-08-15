from sportsedge.ufc_engine import FighterSnapshot, FightContext
from sportsedge.ufc_runtime import evaluate_h2h
from sportsedge.ufc_source import OddsQuote


def fighter(name, elo, missingness=0.0):
    return FighterSnapshot(
        name=name, age=30, height_in=70, reach_in=72, stance="Orthodox",
        wins=12, losses=3, sig_strikes_landed_pm=4.0, sig_strikes_absorbed_pm=3.0,
        sig_strike_accuracy=0.50, sig_strike_defense=0.55, takedowns_per_15=1.5,
        takedown_accuracy=0.40, takedown_defense=0.70, submissions_per_15=0.4,
        recent_win_rate=0.70, strength_of_schedule=0.60, elo=elo,
        days_since_last_fight=150, missingness=missingness,
    )


def quotes(a=-110, b=-110):
    return [
        OddsQuote("e1", "2026-08-15T23:00:00Z", "Alpha", "Beta", "draftkings", "h2h", "Alpha", a),
        OddsQuote("e1", "2026-08-15T23:00:00Z", "Alpha", "Beta", "draftkings", "h2h", "Beta", b),
    ]


def test_runtime_matches_names_and_generates_two_sides():
    out = evaluate_h2h(fighters=[fighter("Alpha", 1650), fighter("Beta", 1450)], quotes=quotes(), n_sims=1000)
    assert len(out) == 2
    assert {x.fighter for x in out} == {"Alpha", "Beta"}
    assert all(0 <= x.model_probability <= 1 for x in out)


def test_uncertain_challenger_fails_closed():
    out = evaluate_h2h(
        fighters=[fighter("Alpha", 1650, missingness=0.9), fighter("Beta", 1450, missingness=0.9)],
        quotes=quotes(+120, -140), max_uncertainty=0.20, n_sims=500,
    )
    assert not any(x.passed for x in out)


def test_context_can_be_supplied_by_pair():
    key = frozenset(("alpha", "beta"))
    out = evaluate_h2h(
        fighters=[fighter("Alpha", 1600), fighter("Beta", 1500)],
        quotes=quotes(), contexts={key: FightContext(rounds=5, title_fight=True)}, n_sims=500,
    )
    assert len(out) == 2
