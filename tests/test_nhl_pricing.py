import pytest
from sportsedge.sports.nhl.markets import OutcomeProbability
from sportsedge.sports.nhl.pricing import NHLQuote, american_profit, american_from_probability, price_outcome


def q(odds=-110):
    return NHLQuote("TOTAL", "OVER 6", odds, "fixture-book", "2026-10-10T00:00:00Z")


def test_american_helpers():
    assert american_profit(-200) == .5
    assert american_profit(150) == 1.5
    assert american_from_probability(.5) == -100
    assert american_from_probability(.6) == -150


def test_price_preserves_push_mass_and_uses_decisive_fair_probability():
    p = price_outcome(OutcomeProbability(.50, .10, .40), q(100))
    assert p.model_push == .10
    assert p.fair_probability == pytest.approx(.50 / .90)
    assert p.expected_value == pytest.approx(.10)
    assert p.qualification_score is None


def test_score_b_is_qualification_only_and_price_invariant():
    outcome = OutcomeProbability(.55, 0, .45)
    plus_money = price_outcome(outcome, q(200), qualification_score=82)
    heavy_juice = price_outcome(outcome, q(-200), qualification_score=82)
    different_probability = price_outcome(OutcomeProbability(.70, 0, .30), q(150), qualification_score=82)
    assert plus_money.expected_value != heavy_juice.expected_value
    assert plus_money.fair_probability != different_probability.fair_probability
    assert plus_money.edge_score == heavy_juice.edge_score == different_probability.edge_score == 82.0
    assert plus_money.qualification_score == 82.0
    assert plus_money.score_label == "RUN_IT_SCORE_V2"


def test_score_b_validation_fails_closed():
    outcome = OutcomeProbability(.55, 0, .45)
    with pytest.raises(ValueError, match="qualification_score"):
        price_outcome(outcome, q(100), qualification_score=101)
    with pytest.raises(ValueError, match="qualification_score"):
        price_outcome(outcome, q(100), qualification_score=float("nan"))


def test_quote_fails_closed_without_provenance_or_valid_odds():
    with pytest.raises(ValueError):
        NHLQuote("ML", "HOME", -110, "", "2026-01-01T00:00:00Z").validate()
    with pytest.raises(ValueError):
        NHLQuote("ML", "HOME", 50, "book", "2026-01-01T00:00:00Z").validate()


def test_quote_requires_timezone_aware_capture():
    q1 = NHLQuote("TOTAL", "OVER 6.5", -110, "book", "2026-09-24T10:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        q1.validate()


def test_quote_freshness_rejects_stale_and_future():
    from sportsedge.sports.nhl.pricing import validate_quote_freshness
    q1 = NHLQuote("TOTAL", "OVER 6.5", -110, "book", "2026-09-24T10:00:00Z", "feed-v1")
    validate_quote_freshness(q1, as_of="2026-09-24T10:04:59Z", max_age_seconds=300)
    with pytest.raises(ValueError, match="stale"):
        validate_quote_freshness(q1, as_of="2026-09-24T10:05:01Z", max_age_seconds=300)
    with pytest.raises(ValueError, match="future"):
        validate_quote_freshness(q1, as_of="2026-09-24T09:59:59Z", max_age_seconds=300)
