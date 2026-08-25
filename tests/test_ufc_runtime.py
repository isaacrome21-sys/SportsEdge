from sportsedge.ufc_engine import FighterSnapshot, FightContext
from sportsedge.ufc_runtime import enforce_model_promotion, evaluate_h2h, _stable_seed
from sportsedge.ufc_source import OddsQuote
from sportsedge.ufc_training import LogisticArtifact


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


def test_monte_carlo_recenters_to_ensemble_probability():
    artifact = LogisticArtifact(
        feature_names=("elo_diff",), coefficients=(0.0,), intercept=2.197224577,
        means=(0.0,), scales=(1.0,),
    )
    out = evaluate_h2h(
        fighters=[fighter("Alpha", 1650), fighter("Beta", 1450)],
        quotes=quotes(), artifact=artifact, n_sims=5000,
    )
    alpha = next(x for x in out if x.fighter == "Alpha")
    assert alpha.trained_probability is not None
    assert abs(alpha.trained_probability - 0.9) < 1e-6
    assert abs(alpha.monte_carlo_probability - alpha.model_probability) < 0.05


def test_monte_carlo_seed_is_cross_process_stable():
    assert _stable_seed("e1", "alpha", "beta", "draftkings") == 2031464258


def test_unpromoted_model_cannot_emit_official_bet():
    out = evaluate_h2h(
        fighters=[fighter("Alpha", 1750), fighter("Beta", 1400)],
        quotes=quotes(+150, -170), n_sims=1000,
    )
    gated = enforce_model_promotion(
        out,
        {"promoted": False, "status": "UNVERIFIED", "blockers": ["CLOSING_ODDS_PROVENANCE_UNVERIFIED"]},
    )
    assert not any(x.passed for x in gated)
    assert all("MODEL_UNPROMOTED" in x.reason for x in gated)


def test_promoted_model_preserves_truth_gate_decisions():
    out = evaluate_h2h(
        fighters=[fighter("Alpha", 1750), fighter("Beta", 1400)],
        quotes=quotes(+150, -170), n_sims=1000,
    )
    gated = enforce_model_promotion(out, {"promoted": True, "status": "PROMOTED", "blockers": []})
    assert gated == out
