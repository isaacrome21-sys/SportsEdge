import pytest

from sportsedge.nfl_run_it_scoring import SCORE_LABEL, NflRunItScoreError, american_from_probability, price_run_it_pick, transparent_score


def test_fair_price_preserves_push_mass_on_decisive_basis():
    p = price_run_it_pick(estimate_p=0.60, push_p=0.20, price_american=-110, market_no_vig_p=0.50)
    assert p.loss_p == pytest.approx(0.20)
    assert p.fair_probability == pytest.approx(0.75)
    assert p.fair_american == -300
    assert p.edge_probability_points == pytest.approx(0.25)
    assert p.ev_per_dollar == pytest.approx(0.60 * (100 / 110) - 0.20)


def test_zero_ev_is_score_50_and_score_is_bounded():
    assert transparent_score(0.0) == 50
    assert transparent_score(1.0) == 100
    assert transparent_score(-1.0) == 0


def test_score_is_monotone_in_ev_and_explicitly_not_probability():
    assert transparent_score(0.01) < transparent_score(0.05) < transparent_score(0.10)
    p = price_run_it_pick(estimate_p=0.55, push_p=0.0, price_american=100, market_no_vig_p=0.50)
    assert p.score_0_100 == 70
    assert p.score_label == SCORE_LABEL
    assert p.score_0_100 != round(p.estimate_p * 100)


def test_fair_american_helpers():
    assert american_from_probability(0.50) == -100
    assert american_from_probability(0.60) == -150
    assert american_from_probability(0.40) == 150


def test_invalid_mass_market_probability_and_odds_fail_closed():
    with pytest.raises(NflRunItScoreError, match="invalid win/push mass"):
        price_run_it_pick(estimate_p=0.9, push_p=0.2, price_american=-110, market_no_vig_p=0.5)
    with pytest.raises(NflRunItScoreError, match="market_no_vig_p"):
        price_run_it_pick(estimate_p=0.5, push_p=0.0, price_american=-110, market_no_vig_p=1.0)
    with pytest.raises(NflRunItScoreError, match="American odds"):
        price_run_it_pick(estimate_p=0.5, push_p=0.0, price_american=50, market_no_vig_p=0.5)
