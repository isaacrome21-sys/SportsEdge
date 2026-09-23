import pytest

from sportsedge.nfl_run_it_scoring import (
    QUALIFICATION_FLAGS,
    SCORE_LABEL,
    NflRunItScoreError,
    american_from_probability,
    price_run_it_pick,
    qualification_role_score,
)


def _flags(**overrides):
    flags = {name: True for name in QUALIFICATION_FLAGS}
    flags.update(overrides)
    return flags


def test_fair_price_preserves_push_mass_on_decisive_basis():
    p = price_run_it_pick(estimate_p=0.60, push_p=0.20, price_american=-110,
                          market_no_vig_p=0.50, qualification_flags=_flags())
    assert p.loss_p == pytest.approx(0.20)
    assert p.fair_probability == pytest.approx(0.75)
    assert p.fair_american == -300
    assert p.edge_probability_points == pytest.approx(0.25)
    assert p.ev_per_dollar == pytest.approx(0.60 * (100 / 110) - 0.20)


def test_score_uses_only_frozen_qualification_role_flags():
    assert qualification_role_score(_flags()) == 100
    assert qualification_role_score(_flags(role_stable=False)) == 88
    assert qualification_role_score({name: False for name in QUALIFICATION_FLAGS}) == 0


def test_score_is_independent_of_ev_edge_and_price():
    flags = _flags(matchup_supported=False)
    a = price_run_it_pick(estimate_p=0.55, push_p=0.0, price_american=100,
                          market_no_vig_p=0.50, qualification_flags=flags)
    b = price_run_it_pick(estimate_p=0.75, push_p=0.0, price_american=200,
                          market_no_vig_p=0.20, qualification_flags=flags)
    assert a.ev_per_dollar != b.ev_per_dollar
    assert a.edge_probability_points != b.edge_probability_points
    assert a.score_0_100 == b.score_0_100
    assert a.score_label == SCORE_LABEL


def test_fair_american_helpers():
    assert american_from_probability(0.50) == -100
    assert american_from_probability(0.60) == -150
    assert american_from_probability(0.40) == 150


def test_invalid_mass_market_odds_and_flag_schema_fail_closed():
    with pytest.raises(NflRunItScoreError, match="invalid win/push mass"):
        price_run_it_pick(estimate_p=0.9, push_p=0.2, price_american=-110,
                          market_no_vig_p=0.5, qualification_flags=_flags())
    with pytest.raises(NflRunItScoreError, match="market_no_vig_p"):
        price_run_it_pick(estimate_p=0.5, push_p=0.0, price_american=-110,
                          market_no_vig_p=1.0, qualification_flags=_flags())
    with pytest.raises(NflRunItScoreError, match="American odds"):
        price_run_it_pick(estimate_p=0.5, push_p=0.0, price_american=50,
                          market_no_vig_p=0.5, qualification_flags=_flags())
    bad = _flags()
    bad.pop("pit_safe")
    with pytest.raises(NflRunItScoreError, match="frozen schema"):
        qualification_role_score(bad)
