from sportsedge.mlb.nrfi_market_consensus import (
    MarketConsensus,
    TwoWayQuote,
    american_to_implied_prob,
    build_consensus,
    clv_probability_delta,
    movement_signal,
    price_edge,
    proportional_devig,
    release_gate,
)


def test_american_probability_conversion():
    assert round(american_to_implied_prob(-150), 6) == 0.6
    assert round(american_to_implied_prob(+150), 6) == 0.4


def test_two_way_devig_sums_to_one():
    nrfi, yrfi, overround = proportional_devig(-130, +100)
    assert round(nrfi + yrfi, 12) == 1.0
    assert overround > 0


def test_consensus_weights_sharp_books_but_shrinks_outlier():
    quotes = [
        TwoWayQuote("Pinnacle", -150, +120),
        TwoWayQuote("Circa", -145, +115),
        TwoWayQuote("DraftKings", -120, -105),
        TwoWayQuote("FanDuel", -118, -108),
    ]
    c = build_consensus(quotes)
    assert c.books_used == 4
    assert 0.5 < c.nrfi_consensus_prob < 0.65
    assert c.dispersion > 0
    assert abs((c.nrfi_consensus_prob + c.yrfi_consensus_prob) - 1.0) < 1e-12


def test_consensus_requires_multiple_books():
    try:
        build_consensus([TwoWayQuote("DraftKings", -120, -105)])
    except ValueError as exc:
        assert "At least two sportsbooks" in str(exc)
    else:
        raise AssertionError("single-book consensus must fail closed")


def test_release_gate_requires_model_edge_and_tradable_ev():
    c = build_consensus([
        TwoWayQuote("Pinnacle", -125, -101),
        TwoWayQuote("Circa", -124, -102),
        TwoWayQuote("DraftKings", -120, -105),
    ])
    edge = price_edge(model_nrfi_prob=0.59, consensus=c, offered_nrfi_american=-110)
    passed, reasons = release_gate(edge, c)
    assert passed
    assert reasons == ()


def test_release_gate_rejects_market_disagreement():
    c = build_consensus([
        TwoWayQuote("Pinnacle", -180, +145),
        TwoWayQuote("Circa", -105, -120),
        TwoWayQuote("DraftKings", +100, -130),
    ])
    edge = price_edge(model_nrfi_prob=0.70, consensus=c, offered_nrfi_american=-110)
    passed, reasons = release_gate(edge, c)
    assert not passed
    assert "MARKET_DISAGREEMENT_HIGH" in reasons


def test_movement_and_clv_are_probability_space():
    opening = build_consensus([
        TwoWayQuote("Pinnacle", -115, -110),
        TwoWayQuote("Circa", -114, -111),
    ])
    current = build_consensus([
        TwoWayQuote("Pinnacle", -140, +110),
        TwoWayQuote("Circa", -138, +108),
    ])
    assert movement_signal(opening, current) == "STEAM_NRFI"
    assert clv_probability_delta(opening.nrfi_consensus_prob, current.nrfi_consensus_prob, "NRFI") > 0
    assert clv_probability_delta(opening.nrfi_consensus_prob, current.nrfi_consensus_prob, "YRFI") < 0


def test_market_layer_is_not_model_eligibility():
    c = build_consensus([
        TwoWayQuote("Pinnacle", -130, +102),
        TwoWayQuote("Circa", -128, +100),
        TwoWayQuote("DraftKings", -125, -102),
    ])
    assert isinstance(c, MarketConsensus)
    # Contract test: this layer exposes market pricing only. It has no promotion or
    # eligibility field and cannot independently promote a frozen candidate model.
    assert not hasattr(c, "eligible")
    assert not hasattr(c, "promotion_state")
