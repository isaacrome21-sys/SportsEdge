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


def test_score_is_bounded_and_explicitly_not_probability():
    hi = price_outcome(OutcomeProbability(.9, 0, .1), q(200))
    lo = price_outcome(OutcomeProbability(.1, 0, .9), q(-200))
    assert hi.edge_score == 100
    assert lo.edge_score == 0
    assert hi.score_label == "TRANSPARENT_EV_SCORE_V1"


def test_quote_fails_closed_without_provenance_or_valid_odds():
    with pytest.raises(ValueError):
        NHLQuote("ML", "HOME", -110, "", "2026-01-01T00:00:00Z").validate()
    with pytest.raises(ValueError):
        NHLQuote("ML", "HOME", 50, "book", "2026-01-01T00:00:00Z").validate()


def test_quote_requires_timezone_aware_capture():
    from sportsedge.sports.nhl.pricing import NHLQuote
    import pytest
    q=NHLQuote("TOTAL","OVER 6.5",-110,"book","2026-09-24T10:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        q.validate()


def test_quote_freshness_rejects_stale_and_future():
    from sportsedge.sports.nhl.pricing import NHLQuote, validate_quote_freshness
    import pytest
    q=NHLQuote("TOTAL","OVER 6.5",-110,"book","2026-09-24T10:00:00Z","feed-v1")
    validate_quote_freshness(q, as_of="2026-09-24T10:04:59Z", max_age_seconds=300)
    with pytest.raises(ValueError, match="stale"):
        validate_quote_freshness(q, as_of="2026-09-24T10:05:01Z", max_age_seconds=300)
    with pytest.raises(ValueError, match="future"):
        validate_quote_freshness(q, as_of="2026-09-24T09:59:59Z", max_age_seconds=300)
