from sportsedge.sports.nhl.markets import OutcomeProbability
from sportsedge.sports.nhl.pricing import NHLQuote
from sportsedge.sports.nhl.run_it import run_it_row, rank_scored


def test_supported_market_prices_without_manufacturing_score():
    q = NHLQuote("TOTAL", "OVER 6.5", 100, "fixture", "2026-10-10T00:00:00Z")
    row = run_it_row("TOTAL", "OVER 6.5", OutcomeProbability(.55, 0, .45), q)
    assert row.status == "PRICED_NO_SCORE"
    assert row.price is not None
    assert row.price.expected_value > 0
    assert row.price.qualification_score is None


def test_supported_market_scores_only_with_upstream_qualification():
    q = NHLQuote("TOTAL", "OVER 6.5", 100, "fixture", "2026-10-10T00:00:00Z")
    row = run_it_row(
        "TOTAL", "OVER 6.5", OutcomeProbability(.55, 0, .45), q,
        qualification_score=84,
    )
    assert row.status == "SCORED"
    assert row.price.qualification_score == 84.0


def test_missing_probability_or_quote_fails_closed():
    q = NHLQuote("TOTAL", "OVER 6.5", -110, "fixture", "2026-10-10T00:00:00Z")
    assert run_it_row("TOTAL", "OVER 6.5", None, q).status == "NO_MODEL_PROBABILITY"
    assert run_it_row("TOTAL", "OVER 6.5", OutcomeProbability(.5, 0, .5), None).status == "NO_MARKET_QUOTE"


def test_engine_backed_player_market_requires_probability():
    row = run_it_row("PLAYER_POINTS", "P1 OVER .5", None, None)
    assert row.status == "NO_MODEL_PROBABILITY"


def test_unsupported_market_is_explicit():
    row = run_it_row("GOALIE_SAVES", "G1 OVER 27.5", None, None)
    assert row.status == "UNSUPPORTED"


def test_binding_mismatch_rejected_and_scored_rows_rank_first():
    good = NHLQuote("TOTAL", "OVER 6.5", 100, "fixture", "2026-10-10T00:00:00Z")
    try:
        run_it_row("TOTAL", "UNDER 6.5", OutcomeProbability(.5, 0, .5), good)
        assert False
    except ValueError:
        pass
    scored = run_it_row(
        "TOTAL", "OVER 6.5", OutcomeProbability(.55, 0, .45), good,
        qualification_score=80,
    )
    priced = run_it_row("TOTAL", "OVER 6.5", OutcomeProbability(.80, 0, .20), good)
    unsupported = run_it_row("GOALIE_SAVES", "G1 OVER 27.5", None, None)
    assert rank_scored([unsupported, priced, scored])[0] == scored


def test_equal_score_price_economics_only_break_presentation_tie():
    plus = NHLQuote("TOTAL", "OVER 6.5", 150, "fixture", "2026-10-10T00:00:00Z")
    minus = NHLQuote("TOTAL", "OVER 6.5", -150, "fixture", "2026-10-10T00:00:00Z")
    outcome = OutcomeProbability(.55, 0, .45)
    high_ev = run_it_row("TOTAL", "OVER 6.5", outcome, plus, qualification_score=82)
    low_ev = run_it_row("TOTAL", "OVER 6.5", outcome, minus, qualification_score=82)
    assert high_ev.price.qualification_score == low_ev.price.qualification_score == 82.0
    assert high_ev.price.expected_value > low_ev.price.expected_value
    assert rank_scored([low_ev, high_ev]) == [high_ev, low_ev]
